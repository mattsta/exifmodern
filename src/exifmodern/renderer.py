"""ExifTool-compatible renderers over modern read graphs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    GroupName,
    ReadGraph,
    ReadTag,
    TagName,
    TagValue,
)

type JsonRecord = dict[str, TagValue]
type RequestArg = str
type RenderIssueKind = Literal["absent_source_data", "missing_parser_coverage"]

if TYPE_CHECKING:
    from exifmodern.public_interface.output_policy import PublicOutputSuppression

type _PublicOutputSuppressionForTag = Callable[[ReadTag], PublicOutputSuppression | None]


@dataclass(frozen=True)
class RequestedTag:
    group: GroupName | None
    name: TagName


@dataclass(frozen=True)
class RenderIssue:
    requested_tag: RequestedTag
    kind: RenderIssueKind
    message: str


@dataclass(frozen=True)
class RenderOptions:
    group_names: bool
    duplicate_tags: bool
    group_family: int | None = None
    include_unknown_tags: bool = False


IGNORED_REQUEST_OPTIONS = frozenset(("-json", "-a", "-s", "-G1", "-G4", "-u", "-U"))
UNKNOWN_REQUEST_OPTIONS = frozenset(("-u", "-U", "-unknown", "-unknown2"))
_EXIFTOOL_JSON_NUMBER_RE = re.compile(
    r"-?(?:\d|[1-9]\d{1,14})(?:\.\d{1,16})?(?:[eE][+-]?\d{1,3})?",
)
_PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG: _PublicOutputSuppressionForTag | None = None


def requested_tags_from_args(args: tuple[RequestArg, ...]) -> list[RequestedTag]:
    tags: list[RequestedTag] = []
    for arg in args:
        tag = requested_tag_from_arg(arg)
        if tag is not None:
            tags.append(tag)
    return tags


def requested_tag_from_arg(arg: RequestArg) -> RequestedTag | None:
    if is_ignored_request_option(arg) or not arg.startswith("-"):
        return None
    tag_arg = arg[1:]
    if ":" not in tag_arg:
        return RequestedTag(group=None, name=tag_arg)
    group, name = tag_arg.split(":", 1)
    return RequestedTag(group=group, name=name)


def is_ignored_request_option(arg: RequestArg) -> bool:
    return arg in IGNORED_REQUEST_OPTIONS or arg.lower() in UNKNOWN_REQUEST_OPTIONS


def graph_record_for_request(
    graph: ReadGraph,
    source_file: str,
    args: tuple[RequestArg, ...],
) -> tuple[JsonRecord, list[RenderIssue]]:
    options = render_options_from_args(args)
    duplicate_groups = duplicate_output_groups(graph)
    record: JsonRecord = {"SourceFile": source_file}
    issues: list[RenderIssue] = []
    requested_tags = requested_tags_from_args(args)
    if not requested_tags:
        seen_default_tag_names: set[TagName] = set()
        for tag in graph.tags:
            if skips_output_tag(tag, options, seen_default_tag_names):
                continue
            record[record_key_for_unfiltered_tag(tag, options, duplicate_groups)] = tag.value
        return record, issues
    for requested_tag in requested_tags:
        tags = find_graph_tags(graph, requested_tag, options)
        if not tags:
            issues.append(classify_missing_tag(graph, requested_tag))
            continue
        for tag in tags:
            record[record_key_for_tag(tag, requested_tag, options, duplicate_groups)] = tag.value
    return record, issues


def render_options_from_args(args: tuple[RequestArg, ...]) -> RenderOptions:
    include_unknown_tags = any(arg in UNKNOWN_REQUEST_OPTIONS for arg in args) or any(
        arg.lower() in UNKNOWN_REQUEST_OPTIONS for arg in args
    )
    if "-G4" in args:
        return RenderOptions(
            group_names=True,
            duplicate_tags="-a" in args,
            group_family=4,
            include_unknown_tags=include_unknown_tags,
        )
    return RenderOptions(
        group_names="-G1" in args,
        duplicate_tags="-a" in args,
        group_family=1,
        include_unknown_tags=include_unknown_tags,
    )


def find_graph_value(graph: ReadGraph, requested_tag: RequestedTag) -> tuple[bool, TagValue]:
    tag = find_graph_tag(graph, requested_tag)
    if tag is None:
        return False, None
    return True, tag.value


def find_graph_tag(graph: ReadGraph, requested_tag: RequestedTag) -> ReadTag | None:
    tags = find_graph_tags(
        graph,
        requested_tag,
        RenderOptions(group_names=False, duplicate_tags=False, group_family=1),
    )
    return tags[0] if tags else None


def find_graph_tags(
    graph: ReadGraph,
    requested_tag: RequestedTag,
    options: RenderOptions,
) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for tag in graph.tags:
        if skips_unknown_tag(tag, options):
            continue
        if tag.name.casefold() != requested_tag.name.casefold():
            continue
        if not tag_matches_request_group(tag, requested_tag, options):
            continue
        tags.append(tag)
        if requested_tag.group is None and not options.duplicate_tags:
            return tags
    return tags


def tag_matches_request_group(
    tag: ReadTag,
    requested_tag: RequestedTag,
    options: RenderOptions,
) -> bool:
    if requested_tag.group is None:
        return True
    if tag.provenance.group == requested_tag.group:
        return True
    if requested_tag.group in {
        tag.provenance.family_0_group,
        tag.provenance.family_1_group,
        tag.provenance.family_2_group,
    }:
        return True
    return (
        options.duplicate_tags
        and requested_tag.group == "IPTC"
        and tag.provenance.group.startswith("IPTC")
        and tag.provenance.group[4:].isdecimal()
    )


def record_key_for_tag(
    tag: ReadTag,
    requested_tag: RequestedTag,
    options: RenderOptions,
    duplicate_groups: dict[TagName, dict[int, GroupName]],
) -> str:
    if options.group_names:
        return f"{record_group_for_tag(tag, options, duplicate_groups)}:{tag.name}"
    return tag.name


def record_key_for_unfiltered_tag(
    tag: ReadTag,
    options: RenderOptions,
    duplicate_groups: dict[TagName, dict[int, GroupName]],
) -> str:
    if options.group_names:
        return f"{record_group_for_tag(tag, options, duplicate_groups)}:{tag.name}"
    return tag.name


def record_group_for_tag(
    tag: ReadTag,
    options: RenderOptions,
    duplicate_groups: dict[TagName, dict[int, GroupName]],
) -> str:
    if options.group_family == 4:
        return family_4_record_group_for_tag(tag, duplicate_groups)
    return tag.provenance.family_1_group or tag.provenance.group


def family_4_record_group_for_tag(
    tag: ReadTag,
    duplicate_groups: dict[TagName, dict[int, GroupName]],
) -> str:
    ordinal = tag.provenance.duplicate_instance_ordinal
    if ordinal is not None and ordinal in duplicate_groups.get(tag.name, {}):
        return duplicate_groups[tag.name][ordinal]
    return tag.provenance.family_4_instance_group or ""


def duplicate_output_groups(graph: ReadGraph) -> dict[TagName, dict[int, GroupName]]:
    """Map source-order duplicate ordinals to ExifTool family-4 output labels."""

    tag_counts: dict[TagName, int] = {}
    ordinal_counts: dict[TagName, int] = {}
    max_ordinals: dict[TagName, int] = {}
    for tag in graph.tags:
        tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1
        ordinal = tag.provenance.duplicate_instance_ordinal
        if ordinal is None:
            continue
        ordinal_counts[tag.name] = ordinal_counts.get(tag.name, 0) + 1
        max_ordinals[tag.name] = max(max_ordinals.get(tag.name, -1), ordinal)

    groups: dict[TagName, dict[int, GroupName]] = {}
    for name, count in tag_counts.items():
        if count <= 1 or ordinal_counts.get(name) != count or max_ordinals.get(name) != count - 1:
            continue
        groups[name] = {ordinal: f"Copy{ordinal + 1}" for ordinal in range(count - 1)}
        groups[name][count - 1] = ""
    return groups


def skips_output_tag(
    tag: ReadTag,
    options: RenderOptions,
    seen_default_tag_names: set[TagName],
) -> bool:
    if skips_unknown_tag(tag, options):
        return True
    return skips_default_duplicate_tag(tag, options, seen_default_tag_names)


def skips_unknown_tag(tag: ReadTag, options: RenderOptions) -> bool:
    if options.include_unknown_tags or not _may_have_public_output_suppression(tag):
        return False
    return _public_output_suppression_for_tag(tag) is not None


def _public_output_suppression_for_tag(tag: ReadTag) -> PublicOutputSuppression | None:
    global _PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG
    if _PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG is None:
        from exifmodern.public_interface.output_policy import public_output_suppression_for_tag

        _PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG = public_output_suppression_for_tag
    return _PUBLIC_OUTPUT_SUPPRESSION_FOR_TAG(tag)


def _may_have_public_output_suppression(tag: ReadTag) -> bool:
    provenance = tag.provenance
    table_name = provenance.table_name
    if table_name in {
        "Image::ExifTool::Apple::Main",
        "Image::ExifTool::Matroska::Main",
        "Image::ExifTool::MacOS::Main",
        "Image::ExifTool::Unknown::Main",
    }:
        return True
    if table_name.startswith("Image::ExifTool::EXE::"):
        return True
    return provenance.source == "jpeg-app1-tiff-dynamic-unknown" and table_name in {
        "Image::ExifTool::Exif::Main",
        "Image::ExifTool::GPS::Main",
    }


def skips_default_duplicate_tag(
    tag: ReadTag,
    options: RenderOptions,
    seen_default_tag_names: set[TagName],
) -> bool:
    if options.duplicate_tags or options.group_names:
        return False
    if tag.name in seen_default_tag_names:
        return True
    seen_default_tag_names.add(tag.name)
    return False


def classify_missing_tag(graph: ReadGraph, requested_tag: RequestedTag) -> RenderIssue:
    if requested_tag.group is not None and not graph_has_group(graph, requested_tag.group):
        return RenderIssue(
            requested_tag=requested_tag,
            kind="absent_source_data",
            message=f"No decoded source data exists for group {requested_tag.group}.",
        )
    return RenderIssue(
        requested_tag=requested_tag,
        kind="missing_parser_coverage",
        message=f"Graph source exists, but {format_requested_tag(requested_tag)} is not decoded.",
    )


def graph_has_group(graph: ReadGraph, group: GroupName) -> bool:
    return any(
        group
        in {
            tag.provenance.group,
            tag.provenance.family_0_group,
            tag.provenance.family_1_group,
            tag.provenance.family_2_group,
        }
        for tag in graph.tags
    )


def render_exiftool_json(record: JsonRecord) -> bytes:
    lines = ["[{"]
    items = list(record.items())
    for index, (key, value) in enumerate(items):
        suffix = "," if index < len(items) - 1 else ""
        lines.append(
            f"  {json.dumps(key, ensure_ascii=False)}: {_render_exiftool_json_value(value)}{suffix}"
        )
    lines.append("}]")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_exiftool_json_value(value: TagValue) -> str:
    rendered = json_render_value(value)
    if isinstance(rendered, list):
        return "[" + ",".join(_render_exiftool_json_scalar(item) for item in rendered) + "]"
    return _render_exiftool_json_scalar(rendered)


def _render_exiftool_json_scalar(value: TagValue) -> str:
    if isinstance(value, float):
        return _render_exiftool_json_float(value)
    if isinstance(value, str) and _EXIFTOOL_JSON_NUMBER_RE.fullmatch(value) is not None:
        return value
    return json.dumps(value, ensure_ascii=False)


def _render_exiftool_json_float(value: float) -> str:
    if value != 0 and abs(value) < 0.001:
        return f"{value:.12f}".rstrip("0").rstrip(".")
    return f"{value:.15g}"


def json_render_value(value: TagValue) -> TagValue:
    if isinstance(value, BinaryTagListValue):
        return [
            f"(Binary data {item.byte_count} bytes, use -b option to extract)"
            for item in value.items
        ]
    if isinstance(value, BinaryTagValue):
        return f"(Binary data {value.byte_count} bytes, use -b option to extract)"
    if isinstance(value, list):
        return list(value)
    return value


def format_render_issues(issues: list[RenderIssue]) -> str:
    return "; ".join(
        f"{issue.kind}: {format_requested_tag(issue.requested_tag)} ({issue.message})"
        for issue in issues
    )


def format_requested_tag(tag: RequestedTag) -> str:
    if tag.group is None:
        return tag.name
    return f"{tag.group}:{tag.name}"
