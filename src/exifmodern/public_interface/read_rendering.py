"""Public read render request and option-diagnostic helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, replace

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    PUBLIC_EVIDENCE_JSON_KEY,
    public_evidence_requested,
    public_evidence_values,
)
from exifmodern.public_api import (
    Diagnostic,
    OutputRenderRequest,
    RenderFormat,
    UnsafeBinaryOutputPolicy,
)
from exifmodern.public_api.models import MetadataReadResult
from exifmodern.public_interface.plot_svg import (
    PlotSvgSettings,
    plot_svg_settings_from_api_options,
)
from exifmodern.public_interface.read_options import group_name_families_from_argparse
from exifmodern.public_interface.unknown_options import (
    PublicUnknownBinaryBlockBlocker,
    PublicUnknownTagOptions,
    public_unknown_tag_options_from_namespace,
)
from exifmodern.read_graph import ReadGraphUnknownTagLevel


def read_result_with_unknown_discovery_diagnostic(
    read_result: MetadataReadResult,
    unknown_tag_options: PublicUnknownTagOptions,
) -> MetadataReadResult:
    blocker = unknown_tag_options.binary_block_discovery_blocker
    if blocker is None:
        return read_result
    if any(diagnostic.code == blocker.code for diagnostic in read_result.diagnostics):
        return read_result
    return replace(
        read_result,
        diagnostics=(
            _unknown_binary_block_discovery_diagnostic(blocker),
            *read_result.diagnostics,
        ),
    )


def read_result_with_public_cli_option_diagnostics(
    read_result: MetadataReadResult,
    unknown_tag_options: PublicUnknownTagOptions,
    *,
    api_options: tuple[str, ...],
    use_modules: tuple[str, ...] = (),
) -> MetadataReadResult:
    api_effects = public_read_api_option_effects(api_options)
    read_result = read_result_with_unknown_discovery_diagnostic(
        read_result,
        _combined_public_unknown_options(unknown_tag_options, api_effects),
    )
    diagnostics = list(read_result.diagnostics)
    status = read_result.status
    if api_effects.unsupported_options and not _diagnostic_code_present(
        diagnostics, "api_read_options_not_connected"
    ):
        diagnostics.insert(
            0,
            api_read_options_not_connected_diagnostic(api_effects.unsupported_options),
        )
        status = "unsupported"
    if use_modules and not _diagnostic_code_present(
        diagnostics, "public_perl_plugin_loading_blocked"
    ):
        diagnostics.insert(0, public_perl_plugin_loading_blocked_diagnostic(use_modules))
        status = "unsupported"
    if tuple(diagnostics) == read_result.diagnostics and status == read_result.status:
        return read_result
    return replace(read_result, status=status, diagnostics=tuple(diagnostics))


def _diagnostic_code_present(diagnostics: Sequence[Diagnostic], code: str) -> bool:
    return any(diagnostic.code == code for diagnostic in diagnostics)


def _unknown_binary_block_discovery_diagnostic(
    blocker: PublicUnknownBinaryBlockBlocker,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details = _debug_evidence_details(
        blocker.evidence_sources,
        include_evidence=include_evidence,
        **options,
    )
    return Diagnostic(
        code=blocker.code,
        message=blocker.message,
        details=details,
    )


def api_read_options_not_connected_diagnostic(
    api_options: tuple[str, ...],
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details = _debug_evidence_details(
        (
            "public.api.read-options.parse",
            "public.api.read-options.surface",
            "public.api.read-options.insert-tag-values",
        ),
        include_evidence=include_evidence,
        **options,
    )
    details["api_options"] = list(api_options)
    return Diagnostic(
        code="api_read_options_not_connected",
        message=(
            "ExifTool -api read options are recognized, but generic API option effects "
            "are not connected to the public metadata read request yet. Arbitrary "
            "UserParam/config-style interpolation is a release blocker, not a "
            "safe-expression VM route."
        ),
        details=details,
    )


def public_perl_plugin_loading_blocked_diagnostic(
    use_modules: tuple[str, ...],
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details = _debug_evidence_details(
        (
            "public.plugin.use.parse",
            "public.plugin.use.docs",
        ),
        include_evidence=include_evidence,
        **options,
    )
    details["modules"] = list(use_modules)
    return Diagnostic(
        code="public_perl_plugin_loading_blocked",
        message=(
            "ExifTool -use plug-in loading is recognized, but public ExifModern does "
            "not load arbitrary Perl modules; this is a release blocker for exact "
            "plug-in compatibility, not a safe-expression VM route."
        ),
        details=details,
    )


def _debug_evidence_details(
    evidence_sources: tuple[str, ...],
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> JsonObject:
    details: JsonObject = {}
    if public_evidence_requested(include_evidence, options):
        details[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(evidence_sources))
    return details


@dataclass(frozen=True)
class PublicReadApiOptionEffects:
    unsupported_options: tuple[str, ...] = ()
    allow_duplicate_tags: bool | None = None
    numeric_output: bool | None = None
    include_unknown_tags: bool | None = None
    unknown_binary_discovery: bool = False
    request_all_level: int | None = None
    request_all_hidden_tag_discovery: bool = False
    unsafe_binary_policy: UnsafeBinaryOutputPolicy | None = None
    output_filter: str | None = None
    output_charset: str | None = None
    language_code: str | None = None
    missing_tag_value: str | None = None
    list_separator: str | None = None
    list_item_index: int | None = None
    plot_svg_settings: PlotSvgSettings | None = None


def _combined_public_unknown_options(
    unknown_tag_options: PublicUnknownTagOptions,
    api_effects: PublicReadApiOptionEffects,
) -> PublicUnknownTagOptions:
    if api_effects.unknown_binary_discovery:
        return unknown_tag_options.with_option("-U")
    if api_effects.include_unknown_tags:
        return unknown_tag_options.with_option("-u")
    return unknown_tag_options


def public_unknown_tag_level_with_api_effects(
    render: OutputRenderRequest,
    api_effects: PublicReadApiOptionEffects,
) -> ReadGraphUnknownTagLevel:
    if api_effects.include_unknown_tags is None:
        return render.unknown_tag_level
    if not api_effects.include_unknown_tags:
        return 0
    if api_effects.unknown_binary_discovery:
        return 2
    return 1


def public_read_api_option_effects(
    api_options: tuple[str, ...],
) -> PublicReadApiOptionEffects:
    unsupported_options: list[str] = []
    allow_duplicate_tags: bool | None = None
    numeric_output: bool | None = None
    include_unknown_tags: bool | None = None
    unknown_binary_discovery = False
    request_all_level: int | None = None
    request_all_hidden_tag_discovery = False
    unsafe_binary_policy: UnsafeBinaryOutputPolicy | None = None
    output_filter: str | None = None
    output_charset: str | None = None
    language_code: str | None = None
    missing_tag_value: str | None = None
    list_separator: str | None = None
    list_item_index: int | None = None
    plot_svg_settings: PlotSvgSettings | None = None
    plot_api_options: list[str] = []

    for raw_option in api_options:
        name, value = _split_public_read_api_option(raw_option)
        normalized_name = name.lower()
        if normalized_name == "plot":
            plot_api_options.append(raw_option)
            continue
        if normalized_name == "charset":
            if value is None:
                unsupported_options.append(raw_option)
            else:
                output_charset = _canonical_public_api_output_charset(value)
            continue
        if normalized_name == "lang":
            if value is None:
                unsupported_options.append(raw_option)
            else:
                language_code = value.replace("-", "_").lower()
            continue
        if normalized_name == "filter":
            output_filter = None if value is None else value
            continue
        if normalized_name == "missingtagvalue":
            if value is None:
                unsupported_options.append(raw_option)
            else:
                missing_tag_value = value
            continue
        if normalized_name in {"listjoin", "listsep"}:
            if value is None:
                unsupported_options.append(raw_option)
            else:
                list_separator = value
            continue
        if normalized_name == "listitem":
            parsed_int = _parse_public_read_api_int(value)
            if parsed_int is None:
                unsupported_options.append(raw_option)
            else:
                list_item_index = parsed_int
            continue
        if normalized_name == "duplicates":
            parsed_bool = _parse_public_read_api_bool(value)
            if parsed_bool is None:
                unsupported_options.append(raw_option)
            else:
                allow_duplicate_tags = parsed_bool
            continue
        if normalized_name == "printconv":
            parsed_bool = _parse_public_read_api_bool(value)
            if parsed_bool is None:
                unsupported_options.append(raw_option)
            else:
                numeric_output = not parsed_bool
            continue
        if normalized_name == "unknown":
            parsed_int = _parse_public_read_api_nonnegative_int(value)
            if parsed_int is None:
                unsupported_options.append(raw_option)
            else:
                include_unknown_tags = parsed_int > 0
                unknown_binary_discovery = parsed_int > 1
            continue
        if normalized_name == "requestall":
            parsed_int = _parse_public_read_api_nonnegative_int(value)
            if parsed_int is None:
                unsupported_options.append(raw_option)
            else:
                request_all_level = parsed_int
                request_all_hidden_tag_discovery = parsed_int > 2
                if request_all_hidden_tag_discovery:
                    unsafe_binary_policy = "request_all_allows_unsafe"
            continue
        unsupported_options.append(raw_option)

    if plot_api_options:
        plot_svg_settings = plot_svg_settings_from_api_options(tuple(plot_api_options)).settings

    return PublicReadApiOptionEffects(
        unsupported_options=tuple(unsupported_options),
        allow_duplicate_tags=allow_duplicate_tags,
        numeric_output=numeric_output,
        include_unknown_tags=include_unknown_tags,
        unknown_binary_discovery=unknown_binary_discovery,
        request_all_level=request_all_level,
        request_all_hidden_tag_discovery=request_all_hidden_tag_discovery,
        unsafe_binary_policy=unsafe_binary_policy,
        output_filter=output_filter,
        output_charset=output_charset,
        language_code=language_code,
        missing_tag_value=missing_tag_value,
        list_separator=list_separator,
        list_item_index=list_item_index,
        plot_svg_settings=plot_svg_settings,
    )


def _split_public_read_api_option(raw_option: str) -> tuple[str, str | None]:
    name, separator, value = raw_option.partition("=")
    if separator != "=":
        return name.removesuffix("^"), "1"
    if name.endswith("^"):
        return name.removesuffix("^"), value
    if value == "":
        return name, None
    return name, value


def _parse_public_read_api_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized_value = value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_public_read_api_nonnegative_int(
    value: str | None,
) -> int | None:
    if value is None or not value.isdecimal():
        return None
    return int(value)


def _parse_public_read_api_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _canonical_public_api_output_charset(value: str) -> str:
    normalized_value = value.strip()
    if normalized_value.lower() in {"latin", "latin1", "cp1252"}:
        return "Latin"
    if normalized_value.lower() in {"utf8", "utf-8", "cp65001"}:
        return "UTF8"
    return normalized_value


def output_render_request_from_args(args: argparse.Namespace) -> OutputRenderRequest:
    render_format: RenderFormat = args.format
    short_output_level = short_output_level_from_argparse(args)
    short_tag_names = short_output_level >= 1
    very_short_output = short_output_level >= 2
    xml_include_table_metadata = args.xml_include_table_metadata
    group_name_families = group_name_families_from_argparse(args)
    if args.tab_format or args.table_format:
        xml_include_table_metadata = True
        if render_format != "xml":
            render_format = "tab"
    allow_duplicate_tags = args.allow_duplicates or render_format == "php"
    if args.table_format:
        short_output_level = min(short_output_level + 2, 3)
        short_tag_names = True
        very_short_output = True
    unknown_tag_options = public_unknown_tag_options_from_namespace(args, "unknown_tag_options")
    render = OutputRenderRequest(
        format=render_format,
        include_group_names=args.group_names or bool(group_name_families),
        include_unknown_tags=unknown_tag_options.include_suppressed_unknown_tags,
        unknown_tag_level=unknown_tag_options.exiftool_unknown_level,
        allow_duplicate_tags=allow_duplicate_tags,
        group_name_families=group_name_families,
        short_output_level=short_output_level,
        short_tag_names=short_tag_names,
        very_short_output=very_short_output,
        sort_output=args.sort_output,
        numeric_output=args.numeric_output,
        csv_delimiter=args.csv_delim,
        list_separator=args.list_separator or ", ",
        join_list_values=args.list_separator is not None,
        binary_output=args.binary_output,
        suppress_binary_tags=args.suppress_binary_tags,
        output_file_routing=args.output_file_routing,
        xml_tag_id_format=args.xml_tag_id_format,
        xml_include_table_metadata=xml_include_table_metadata,
        structured_output=args.structured_output,
        list_item_index=args.list_item_index,
        missing_tag_value="-" if args.force_print else None,
        ignore_minor_errors=args.ignore_minor_errors,
        verbose_level=args.verbose_level,
        html_dump_base=getattr(args, "html_dump_base", 0),
        extract_embedded_level=args.extract_embedded_level,
        scan_for_xmp=args.scan_for_xmp,
        output_charset=getattr(args, "output_charset", "UTF8"),
        language_code=getattr(args, "read_language_code", "en"),
        internal_charset_options=tuple(getattr(args, "internal_charset_options", ())),
    )
    return output_render_request_with_api_effects(render, tuple(args.api_options))


def short_output_level_from_argparse(args: argparse.Namespace) -> int:
    levels: list[int] = args.short_output_levels
    level = 0
    for requested_level in levels:
        if requested_level == 1 and level > 0:
            level += 1
        elif requested_level == 1:
            level = 1
        else:
            level = requested_level
    if args.very_short:
        level += 2
    return min(level, 3)


def output_render_request_with_api_effects(
    render: OutputRenderRequest,
    api_options: tuple[str, ...],
) -> OutputRenderRequest:
    api_effects = public_read_api_option_effects(api_options)
    output_file_routing = render.output_file_routing
    if api_effects.unsafe_binary_policy is not None:
        output_file_routing = replace(
            output_file_routing,
            unsafe_binary_policy=api_effects.unsafe_binary_policy,
        )
    return replace(
        render,
        allow_duplicate_tags=(
            render.allow_duplicate_tags
            if api_effects.allow_duplicate_tags is None
            else api_effects.allow_duplicate_tags
        ),
        numeric_output=(
            render.numeric_output
            if api_effects.numeric_output is None
            else api_effects.numeric_output
        ),
        include_unknown_tags=(
            render.include_unknown_tags
            if api_effects.include_unknown_tags is None
            else api_effects.include_unknown_tags
        ),
        unknown_tag_level=public_unknown_tag_level_with_api_effects(render, api_effects),
        request_all_level=(
            render.request_all_level
            if api_effects.request_all_level is None
            else api_effects.request_all_level
        ),
        output_file_routing=output_file_routing,
        output_filter=(
            render.output_filter if api_effects.output_filter is None else api_effects.output_filter
        ),
        output_charset=(
            render.output_charset
            if api_effects.output_charset is None
            else api_effects.output_charset
        ),
        language_code=(
            render.language_code if api_effects.language_code is None else api_effects.language_code
        ),
        missing_tag_value=(
            render.missing_tag_value
            if api_effects.missing_tag_value is None
            else api_effects.missing_tag_value
        ),
        list_separator=(
            render.list_separator
            if api_effects.list_separator is None
            else api_effects.list_separator
        ),
        join_list_values=render.join_list_values or api_effects.list_separator is not None,
        list_item_index=(
            render.list_item_index
            if api_effects.list_item_index is None
            else api_effects.list_item_index
        ),
        plot_svg_settings=(
            render.plot_svg_settings
            if api_effects.plot_svg_settings is None
            else api_effects.plot_svg_settings
        ),
    )
