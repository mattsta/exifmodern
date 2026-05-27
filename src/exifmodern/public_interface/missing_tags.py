"""Oracle-compatible forced missing-tag projection helpers."""

from __future__ import annotations

from typing import Literal

from exifmodern.renderer import RenderIssue

type ForcedMissingRenderFormat = Literal["text", "json", "xml", "csv", "tab", "html", "php"]
type ForcedMissingGroupFamily = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8]


def forced_missing_record_key(
    issue: RenderIssue,
    *,
    include_group_names: bool,
    render_format: ForcedMissingRenderFormat,
    group_name_families: tuple[ForcedMissingGroupFamily, ...] = (),
) -> str:
    requested_tag = issue.requested_tag
    if not include_group_names and render_format != "xml":
        return requested_tag.name
    if requested_tag.group is None:
        group_name = forced_missing_group_name(
            issue,
            render_format=render_format,
            group_name_families=group_name_families,
        )
        return f"{group_name}:{requested_tag.name}" if group_name else requested_tag.name
    return f"{requested_tag.group}:{requested_tag.name}"


def forced_missing_group_name(
    issue: RenderIssue,
    *,
    render_format: ForcedMissingRenderFormat = "text",
    group_name_families: tuple[ForcedMissingGroupFamily, ...] = (),
) -> str:
    if issue.requested_tag.group is not None:
        return issue.requested_tag.group
    if 4 not in group_name_families:
        return "Unknown"
    # JSON/PHP synthesize Copy0 for missing family-4 groups; CSV keeps the tag
    # ungrouped, and text/tab/HTML expose the empty family-4 group.
    if render_format in {"json", "php"}:
        return "Copy0"
    if render_format in {"csv", "tab", "text", "html"}:
        return ""
    return "Unknown"
