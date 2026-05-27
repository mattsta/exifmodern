"""Text renderer for production-facing capability query results."""

from __future__ import annotations

from exifmodern.public_api.models import CapabilityQueryResult


def render_capability_query_text(result: CapabilityQueryResult) -> str:
    lines = ["ExifModern public capabilities:"]
    for capability in result.capabilities:
        lines.append(f"  {capability.name}: {capability.status} - {capability.summary}")
        for surface in capability.surfaces:
            lines.append(f"    {surface.name}: {surface.status} - {surface.summary}")
    if result.tag_lookup_summary is not None:
        summary = result.tag_lookup_summary
        lines.extend(
            (
                "",
                "TagLookup package:",
                f"  path: {summary.package_path}",
                f"  loaded: {_text_bool(summary.package_loaded)}",
                f"  tables: {summary.table_count}",
                f"  writable lookup tags: {summary.lookup_tag_count}",
                f"  exists-only tags: {summary.tag_exists_count}",
                f"  composite modules: {summary.composite_module_count}",
                "",
                "TagLookup query summary:",
                f"  requested tags: {summary.queried_tag_count}",
                f"  wildcard requests: {summary.wildcard_query_count}",
                f"  resolved tags: {summary.resolved_tag_count}",
                f"  exists-only tags: {summary.exists_only_tag_count}",
                f"  missing tags: {summary.missing_tag_count}",
                f"  writable candidates: {summary.writable_candidate_count}",
                f"  writable selections: {summary.writable_selection_count}",
                f"  resolved writable selections: {summary.writable_resolved_count}",
                f"  ambiguous writable selections: {summary.writable_ambiguous_count}",
                f"  blocked writable selections: {summary.writable_blocked_count}",
                f"  missing writable selections: {summary.writable_not_found_count}",
            )
        )
    if result.tag_lookup_capabilities:
        lines.extend(("", "TagLookup tag capabilities:"))
        for tag_lookup_capability in result.tag_lookup_capabilities:
            lines.append(
                "  "
                f"{tag_lookup_capability.tag_name}: {tag_lookup_capability.status}; "
                f"exists={_text_bool(tag_lookup_capability.exists)}; "
                f"writable={_text_bool(tag_lookup_capability.writable)}; "
                f"wildcard={_text_bool(tag_lookup_capability.wildcard)}; "
                f"matches={_text_join(tag_lookup_capability.matched_tag_names)}"
            )
            for candidate in tag_lookup_capability.candidates:
                lines.append(
                    "    "
                    f"{candidate.table_name} #{candidate.table_number} "
                    f"ids={_text_join(candidate.tag_ids)}"
                )
    if result.tag_lookup_writable_selections:
        lines.extend(("", "TagLookup writable selections:"))
        for selection in result.tag_lookup_writable_selections:
            lines.append(
                "  "
                f"{selection.request.raw_name}: {selection.outcome}; "
                f"route={selection.route}; "
                f"selected={len(selection.selected_candidates)}"
            )
            for blocker in selection.blockers:
                lines.append(f"    blocker {blocker.code}: {blocker.detail}")
            for candidate in selection.selected_candidates:
                lines.append(
                    "    "
                    f"{candidate.table_name} #{candidate.table_number} "
                    f"ids={_text_join(candidate.tag_ids)}"
                )
    if result.diagnostics:
        lines.extend(("", "Diagnostics:"))
        for diagnostic in result.diagnostics:
            lines.append(f"  {diagnostic.code}: {diagnostic.message}")
    return "\n".join(lines) + "\n"


def _text_bool(value: bool) -> str:
    return "yes" if value else "no"


def _text_join(values: tuple[str, ...]) -> str:
    if not values:
        return "-"
    return ",".join(values)
