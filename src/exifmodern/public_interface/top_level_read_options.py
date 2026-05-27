"""Top-level ExifTool-style public read option scanning helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.public_api import (
    MetadataReadRequest,
    OutputFileRoutingRequest,
    OutputRenderRequest,
    RenderFormat,
)
from exifmodern.public_api.models import (
    ExtensionFilter,
    PublicCharsetOption,
    PublicCharsetTarget,
    PublicPrintFormatTemplate,
    PublicReadAlternateFile,
    PublicReadCondition,
    PublicReadFileOrder,
    PublicReadSourceFile,
)
from exifmodern.public_interface.conditionals import (
    is_public_alternate_file_option,
    public_alternate_file_slot_deferred_message,
    public_bounded_alternate_file_slot,
)
from exifmodern.public_interface.config_boundary import (
    PublicConfigPluginVmBoundaryContract as PublicConfigPluginVmBoundaryContract,
)
from exifmodern.public_interface.config_boundary import (
    PublicSafeConfigUseOptions as PublicSafeConfigUseOptions,
)
from exifmodern.public_interface.config_boundary import (
    PublicTrustedConfigDefaultArguments as PublicTrustedConfigDefaultArguments,
)
from exifmodern.public_interface.config_boundary import (
    PublicTrustedConfigEffects as PublicTrustedConfigEffects,
)
from exifmodern.public_interface.config_boundary import (
    apply_trusted_public_config_default_arguments,
    parse_safe_public_config_option,
    parse_safe_public_use_option,
    public_config_deferred_message,
    public_use_deferred_message,
    trusted_public_config_effective_args,
    trusted_public_config_expand_shortcut_tokens,
    trusted_public_config_supported_read_extensions,
)
from exifmodern.public_interface.config_boundary import (
    parse_public_safe_config_use_options as parse_public_safe_config_use_options,
)
from exifmodern.public_interface.config_boundary import (
    public_config_plugin_vm_boundary_contract as public_config_plugin_vm_boundary_contract,
)
from exifmodern.public_interface.read_options import (
    append_top_level_read_double_dash_exclusion,
    append_top_level_read_tag,
    is_output_file_routing_option,
    output_file_routing_with_option,
    parse_csv_delimiter_option,
    parse_fast_scan_option,
    parse_group_name_families_option,
    parse_ignore_directory_option,
    parse_list_item_option,
    parse_list_separator_option,
    parse_output_file_routing_value_option,
    parse_read_exclusion_option,
    parse_top_level_extension_filter,
    public_read_tag_exclusions_from_raw,
)
from exifmodern.public_interface.traversal import expand_public_cli_read_paths
from exifmodern.public_interface.unknown_options import (
    PublicUnknownTagOptions,
    public_is_unknown_tag_option,
)
from exifmodern.public_interface.user_params import (
    PublicUserParam,
    parse_public_user_param_argument,
)

READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS = frozenset(
    {
        "--format",
        "--tag",
        "--ext",
        "--extension",
        "--Wext",
        "--tagOutExt",
        "--csv-delim",
    }
)
READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS = frozenset(
    {
        "--group-names",
        "--duplicates",
        "--printConv",
        "--printconv",
        "--allow-duplicates",
        "--short-names",
        "--very-short",
        "--veryShort",
        "--veryshort",
        "--xml-table-metadata",
        "--recursive",
        "--b",
        "--binary",
    }
)


@dataclass(frozen=True)
class PublicParsedCharsetOption:
    charset: str
    raw_option: str
    target: PublicCharsetTarget | None = None


def parse_top_level_read_request(
    args: Sequence[str],
    *,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
) -> MetadataReadRequest:
    paths: list[Path] = []
    tags: list[str] = []
    tag_exclusions: list[str] = []
    render_format: RenderFormat = "text"
    include_group_names = False
    group_name_families: list[Literal[0, 1, 2, 4]] = []
    allow_duplicate_tags = False
    short_output_level = 0
    sort_output = False
    numeric_output = False
    recursive = False
    recurse_dot_directories = False
    csv_delimiter = ","
    list_separator = ", "
    join_list_values = False
    binary_output = False
    suppress_binary_tags = False
    unknown_tag_options = PublicUnknownTagOptions()
    output_file_routing = OutputFileRoutingRequest()
    fast_scan_level: int | None = None
    xml_tag_id_format: Literal["none", "decimal", "hex"] = "none"
    xml_include_table_metadata = False
    structured_output = False
    list_item_index: int | None = None
    missing_tag_value: str | None = None
    print_format_templates: list[PublicPrintFormatTemplate] = []
    verbose_level = 0
    html_dump_base = 0
    extract_embedded_level = 0
    scan_for_xmp = False
    ignore_directories: list[str] = []
    extension_filters: list[ExtensionFilter] = []
    conditions: list[PublicReadCondition] = []
    file_order: list[PublicReadFileOrder] = []
    alternate_files: list[PublicReadAlternateFile] = []
    source_files: list[PublicReadSourceFile] = []
    user_params: list[PublicUserParam] = []
    output_charset = "UTF8"
    language_code = "en"
    internal_charset_options: list[PublicCharsetOption] = []
    default_config_disabled = False

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-json", "-j"}:
            render_format = "json"
            index += 1
            continue
        if arg in {"-X", "-xmlFormat", "-xmlformat"}:
            render_format = "xml"
            include_group_names = True
            allow_duplicate_tags = True
            index += 1
            continue
        if arg in {"-h", "-htmlFormat", "-htmlformat"}:
            render_format = "html"
            index += 1
            continue
        if arg == "-php":
            render_format = "php"
            allow_duplicate_tags = True
            index += 1
            continue
        if is_html_dump_option(arg):
            render_format = "html_dump"
            verbose_level = max(verbose_level, 1)
            html_dump_base = html_dump_base_from_option(arg)
            index += 1
            continue
        if arg == "-plot":
            render_format = "plot"
            index += 1
            continue
        if arg == "-csv":
            render_format = "csv"
            index += 1
            continue
        if arg in {"-b", "-binary"}:
            binary_output = True
            index += 1
            continue
        if arg in {"--b", "--binary"}:
            suppress_binary_tags = True
            index += 1
            continue
        if public_is_unknown_tag_option(arg):
            unknown_tag_options = unknown_tag_options.with_option(arg)
            index += 1
            continue
        if arg.lower() == "-api":
            api_value = parse_top_level_read_api_option(arg, args, index)
            api_user_param = public_api_user_param_argument(api_value)
            if api_user_param is not None:
                user_params.append(parse_public_user_param_argument(api_user_param))
            index += 2
            continue
        if is_top_level_latin_charset_option(arg):
            output_charset = "Latin"
            index += 1
            continue
        if arg.lower() == "-charset":
            charset_option = parse_top_level_charset_option(arg, args, index)
            if charset_option.target is None:
                output_charset = charset_option.charset
            else:
                internal_charset_options.append(
                    PublicCharsetOption(
                        target=charset_option.target,
                        charset=charset_option.charset,
                        raw_option=charset_option.raw_option,
                    )
                )
            index += 2
            continue
        if arg.lower() == "-lang":
            language_code = parse_top_level_language_option(arg, args, index)
            index += 2
            continue
        if arg.lower() == "-config":
            effect = parse_safe_public_config_option(
                arg,
                args,
                index,
                default_config_already_disabled=default_config_disabled,
            )
            default_config_disabled = effect.disable_default_config or default_config_disabled
            index += 2
            continue
        if arg.lower() == "-use":
            parse_safe_public_use_option(arg, args, index)
            index += 2
            continue
        if is_top_level_print_format_option(arg):
            print_format_templates.append(
                load_public_print_format_template(
                    arg,
                    parse_required_top_level_option_value(arg, args, index),
                )
            )
            index += 2
            continue
        parsed_verbose_level = parse_verbose_option(arg)
        if parsed_verbose_level is not None:
            verbose_level = parsed_verbose_level
            index += 1
            continue
        parsed_extract_embedded_level = parse_extract_embedded_option(arg)
        if parsed_extract_embedded_level is not None:
            extract_embedded_level = parsed_extract_embedded_level
            allow_duplicate_tags = True
            index += 1
            continue
        if arg.lower() == "-scanforxmp":
            scan_for_xmp = True
            index += 1
            continue
        if is_top_level_read_deferred_value_option(arg):
            value = parse_required_top_level_option_value(arg, args, index)
            if is_source_file_option(arg):
                source_files.append(PublicReadSourceFile(raw_option=arg, path=Path(value)))
                index += 2
                continue
            if is_user_param_option(arg):
                user_params.append(parse_public_user_param_argument(value))
                index += 2
                continue
            if is_if_condition_option(arg):
                conditions.append(
                    PublicReadCondition(
                        raw_option=arg,
                        expression=value,
                        pass_number=bounded_public_option_suffix(arg, "if"),
                    )
                )
                index += 2
                continue
            if is_file_order_option(arg):
                file_order.append(
                    PublicReadFileOrder(
                        raw_option=arg,
                        tag=value,
                        fast_pass=bounded_public_option_suffix(arg, "fileorder"),
                    )
                )
                index += 2
                continue
            if is_alternate_file_option(arg):
                alternate_files.append(
                    PublicReadAlternateFile(
                        raw_option=arg,
                        path=Path(value),
                        slot=bounded_alternate_file_slot(arg),
                    )
                )
                index += 2
                continue
            raise argparse.ArgumentTypeError(public_read_option_deferred_message(arg))
        if is_top_level_read_deferred_optional_value_option(arg):
            if index + 1 < len(args) and not args[index + 1].startswith("-"):
                index += 2
            else:
                index += 1
            raise argparse.ArgumentTypeError(public_read_option_deferred_message(arg))
        if is_top_level_read_deferred_flag_option(arg):
            raise argparse.ArgumentTypeError(public_read_option_deferred_message(arg))
        if arg.lower() in {"-z", "-zip"}:
            raise argparse.ArgumentTypeError(
                "public compressed metadata routing for -z/-zip is not implemented yet; "
                "the public read path does not yet apply Compress and XMPShorthand "
                "routing for this option"
            )
        if arg == "-P" or arg.lower() == "-preserve":
            index += 1
            continue
        if arg in {"-f", "-forcePrint", "-forceprint"}:
            missing_tag_value = "-"
            index += 1
            continue
        if is_output_file_routing_option(arg):
            output_file_routing = output_file_routing_with_option(
                output_file_routing,
                arg,
                parse_output_file_routing_value_option(arg, args, index),
            )
            index += 2
            continue
        parsed_fast_scan_level = parse_fast_scan_option(arg)
        if parsed_fast_scan_level is not None:
            fast_scan_level = parsed_fast_scan_level
            index += 1
            continue
        if arg in {"-D", "-decimal"}:
            xml_tag_id_format = "decimal"
            index += 1
            continue
        if arg in {"-H", "-hex"}:
            xml_tag_id_format = "hex"
            index += 1
            continue
        if arg in {"-struct", "-structFormat", "-structformat"}:
            structured_output = True
            index += 1
            continue
        if arg in {"-csvDelim", "-csvdelim", "--csv-delim"}:
            csv_delimiter = parse_csv_delimiter_option(arg, args, index)
            index += 2
            continue
        if arg in {"-sort", "-Sort"}:
            sort_output = True
            index += 1
            continue
        if arg == "-n" or arg.lower() == "--printconv":
            numeric_output = True
            index += 1
            continue
        if arg.lower() == "-printconv":
            numeric_output = False
            index += 1
            continue
        if arg in {"-sep", "-separator"}:
            list_separator = parse_list_separator_option(arg, args, index)
            join_list_values = True
            index += 2
            continue
        if arg.lower() == "-listitem":
            list_item_index = parse_list_item_option(arg, args, index)
            index += 2
            continue
        if arg in {"-t", "-tab"}:
            xml_include_table_metadata = True
            if render_format != "xml":
                render_format = "tab"
            index += 1
            continue
        if arg in {"-T", "-table"}:
            xml_include_table_metadata = True
            if render_format != "xml":
                render_format = "tab"
            short_output_level = min(short_output_level + 2, 3)
            index += 1
            continue
        group_name_families_option = parse_group_name_families_option(arg)
        if group_name_families_option is not None:
            include_group_names = True
            group_name_families.extend(group_name_families_option)
            index += 1
            continue
        if arg in {"-a", "-duplicates"}:
            allow_duplicate_tags = True
            index += 1
            continue
        if arg in {"--a", "--duplicates"}:
            allow_duplicate_tags = False
            index += 1
            continue
        parsed_short_output_level = parse_short_output_option(arg)
        if parsed_short_output_level is not None:
            if parsed_short_output_level == 1 and short_output_level > 0:
                short_output_level += 1
            elif parsed_short_output_level == 1:
                short_output_level = 1
            else:
                short_output_level = parsed_short_output_level
            short_output_level = min(short_output_level, 3)
            index += 1
            continue
        if arg in {
            "-S",
            "-veryShort",
            "-veryshort",
            "--veryShort",
            "--veryshort",
            "--very-short",
        }:
            short_output_level = min(short_output_level + 2, 3)
            index += 1
            continue
        if arg in {"-r", "-recurse"}:
            recursive = True
            index += 1
            continue
        if arg in {"-r.", "-recurse."}:
            recursive = True
            recurse_dot_directories = True
            index += 1
            continue
        if arg in {"-i", "-ignore"}:
            ignore_directories.append(parse_ignore_directory_option(arg, args, index))
            index += 2
            continue
        if arg in {"-x", "-exclude"}:
            tag_exclusions.append(parse_read_exclusion_option(arg, args, index))
            index += 2
            continue
        if arg in {"-ext", "-extension", "--ext", "--extension", "-ext+", "-extension+"}:
            extension_filters.append(parse_top_level_extension_filter(arg, args, index))
            index += 2
            continue
        if arg.startswith("--"):
            append_top_level_read_double_dash_exclusion(tag_exclusions, arg)
            index += 1
            continue
        if arg.startswith("-"):
            append_top_level_read_tag(tags, arg)
            index += 1
            continue
        paths.append(Path(arg))
        index += 1

    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")

    render = OutputRenderRequest(
        format=render_format,
        include_group_names=include_group_names,
        allow_duplicate_tags=allow_duplicate_tags,
        group_name_families=tuple(group_name_families),
        short_output_level=short_output_level,
        short_tag_names=short_output_level >= 1,
        very_short_output=short_output_level >= 2,
        sort_output=sort_output,
        numeric_output=numeric_output,
        csv_delimiter=csv_delimiter,
        list_separator=list_separator,
        join_list_values=join_list_values,
        binary_output=binary_output,
        suppress_binary_tags=suppress_binary_tags,
        include_unknown_tags=unknown_tag_options.include_suppressed_unknown_tags,
        unknown_tag_level=unknown_tag_options.exiftool_unknown_level,
        output_file_routing=output_file_routing,
        xml_tag_id_format=xml_tag_id_format,
        xml_include_table_metadata=xml_include_table_metadata,
        structured_output=structured_output,
        list_item_index=list_item_index,
        missing_tag_value=missing_tag_value,
        print_format_templates=tuple(print_format_templates),
        verbose_level=verbose_level,
        html_dump_base=html_dump_base,
        extract_embedded_level=extract_embedded_level,
        scan_for_xmp=scan_for_xmp,
        output_charset=output_charset,
        language_code=language_code,
        internal_charset_options=tuple(internal_charset_options),
    )
    from exifmodern.public_interface.read_rendering import output_render_request_with_api_effects

    render = output_render_request_with_api_effects(render, top_level_read_api_options(args))

    path_tuple = tuple(paths)
    ignore_directory_tuple = tuple(ignore_directories)
    extension_filter_tuple = tuple(extension_filters)
    trusted_supported_extensions = (
        frozenset()
        if trusted_config_effects is None
        else trusted_public_config_supported_read_extensions(trusted_config_effects)
    )
    effective_tags = (
        tuple(tags)
        if trusted_config_effects is None
        else trusted_public_config_expand_shortcut_tokens(tags, trusted_config_effects)
    )
    effective_tag_exclusions = (
        tuple(tag_exclusions)
        if trusted_config_effects is None
        else trusted_public_config_expand_shortcut_tokens(
            tag_exclusions,
            trusted_config_effects,
            remove_value_suffix=True,
            skip_excluded_targets=True,
        )
    )
    return MetadataReadRequest(
        paths=expand_public_cli_read_paths(
            path_tuple,
            recursive=recursive,
            recurse_dot_directories=recurse_dot_directories,
            ignore_directories=ignore_directory_tuple,
            extension_filters=extension_filter_tuple,
            trusted_supported_extensions=trusted_supported_extensions,
        ),
        tags=effective_tags,
        tag_exclusions=public_read_tag_exclusions_from_raw(effective_tag_exclusions),
        recursive=recursive,
        recurse_dot_directories=recurse_dot_directories,
        ignore_directories=ignore_directory_tuple,
        fast_scan_level=fast_scan_level,
        extension_filters=extension_filter_tuple,
        conditions=tuple(conditions),
        file_order=tuple(file_order),
        alternate_files=tuple(alternate_files),
        source_files=tuple(source_files),
        user_params=tuple(user_params),
        render=render,
    )


def parse_top_level_read_request_with_trusted_config_defaults(
    args: Sequence[str],
    trusted_defaults: PublicTrustedConfigDefaultArguments,
) -> MetadataReadRequest:
    """Parse public read args after applying trusted config-defined defaults."""

    return parse_top_level_read_request(
        apply_trusted_public_config_default_arguments(args, trusted_defaults)
    )


def parse_top_level_read_request_with_trusted_config_effects(
    args: Sequence[str],
    trusted_effects: PublicTrustedConfigEffects,
) -> MetadataReadRequest:
    """Parse public read args after applying typed trusted-host config effects."""

    effective_args = trusted_public_config_effective_args(args, trusted_effects)
    return parse_top_level_read_request(effective_args, trusted_config_effects=trusted_effects)


def parse_short_output_option(arg: str) -> int | None:
    token = arg.removeprefix("-")
    if token in {"s", "short"}:
        return 1
    if token in {"s1", "short1"}:
        return 1
    if token in {"s2", "short2"}:
        return 2
    if token in {"s3", "short3"}:
        return 3
    return None


def parse_verbose_option(arg: str) -> int | None:
    if not arg.startswith("-"):
        return None
    body = arg.removeprefix("-").lower()
    if body in {"v", "verbose"}:
        return 1
    if body.startswith("v") and body.removeprefix("v").isdecimal():
        return int(body.removeprefix("v"))
    if body.startswith("verbose") and body.removeprefix("verbose").isdecimal():
        return int(body.removeprefix("verbose"))
    return None


def parse_extract_embedded_option(arg: str) -> int | None:
    if not arg.startswith("-"):
        return None
    body = arg.removeprefix("-").lower()
    if body in {"ee", "extractembedded"}:
        return 1
    if body.startswith("ee") and body.removeprefix("ee").isdecimal():
        return int(body.removeprefix("ee")) or 1
    if body.startswith("extractembedded") and body.removeprefix("extractembedded").isdecimal():
        return int(body.removeprefix("extractembedded")) or 1
    return None


def is_top_level_print_format_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    body = option.removeprefix("-")
    if body in {"p", "p-"}:
        return True
    return body.lower() in {"printformat", "printformat-"}


def is_html_dump_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    body = option.removeprefix("-").lower()
    if not body.startswith("htmldump"):
        return False
    suffix = body.removeprefix("htmldump")
    if suffix == "":
        return True
    return suffix.lstrip("+-").isdecimal()


def html_dump_base_from_option(option: str) -> int:
    body = option.removeprefix("-").lower()
    suffix = body.removeprefix("htmldump")
    if suffix == "":
        return 0
    if not is_html_dump_option(option):
        raise argparse.ArgumentTypeError(f"Invalid -htmlDump offset option: {option}")
    return int(suffix)


def load_public_print_format_template(
    option: str,
    argument: str,
) -> PublicPrintFormatTemplate:
    append_inline_newline = option.removeprefix("-").lower() not in {"p-", "printformat-"}
    if "\n" not in argument:
        path = Path(argument)
        if path.is_file():
            return PublicPrintFormatTemplate(
                source_kind="file",
                raw_argument=argument,
                lines=tuple(path.read_text(encoding="utf-8-sig").splitlines(keepends=True)),
                append_inline_newline=append_inline_newline,
            )
    inline = f"{argument}\n" if append_inline_newline else argument
    return PublicPrintFormatTemplate(
        source_kind="inline",
        raw_argument=argument,
        lines=(inline,),
        append_inline_newline=append_inline_newline,
    )


def top_level_read_requests_binary_suppression(args: Sequence[str]) -> bool:
    return any(arg in {"--b", "--binary"} for arg in args)


def top_level_read_api_options(args: Sequence[str]) -> tuple[str, ...]:
    api_options: list[str] = []
    index = 0
    while index < len(args):
        if args[index].lower() == "-api":
            api_value = parse_top_level_read_api_option(args[index], args, index)
            if public_api_user_param_argument(api_value) is None:
                api_options.append(api_value)
            index += 2
            continue
        index += 1
    return tuple(api_options)


def parse_top_level_read_api_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"{option} requires an API option name or NAME=VALUE")
    value = args[value_index]
    if value.startswith("-"):
        raise argparse.ArgumentTypeError(f"{option} requires an API option name or NAME=VALUE")
    return value


def public_api_user_param_argument(value: str) -> str | None:
    name, separator, assigned_value = value.partition("=")
    if name.lower() != "userparam":
        return None
    if separator != "=":
        return None
    return assigned_value


def is_top_level_latin_charset_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    body = option.removeprefix("-")
    return body == "L" or body.lower() == "latin"


def parse_top_level_charset_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> PublicParsedCharsetOption:
    value = parse_required_top_level_option_value(option, args, index)
    name, separator, charset = value.partition("=")
    if separator != "=":
        return PublicParsedCharsetOption(
            charset=canonical_public_output_charset(value),
            raw_option=value,
        )
    if name.lower() == "exiftool":
        return PublicParsedCharsetOption(
            charset=canonical_public_output_charset(charset),
            raw_option=value,
        )
    target = public_charset_target(name)
    if target is None:
        raise argparse.ArgumentTypeError(f"Unknown type for -charset option: {name}")
    return PublicParsedCharsetOption(
        charset=canonical_public_output_charset(charset),
        raw_option=value,
        target=target,
    )


def parse_top_level_language_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value = parse_required_top_level_option_value(option, args, index)
    return value.replace("-", "_").lower()


def public_charset_target(name: str) -> PublicCharsetTarget | None:
    normalized_name = name.lower()
    if normalized_name == "exif":
        return "EXIF"
    if normalized_name == "filename":
        return "FileName"
    if normalized_name == "id3":
        return "ID3"
    if normalized_name == "iptc":
        return "IPTC"
    if normalized_name == "photoshop":
        return "Photoshop"
    if normalized_name == "quicktime":
        return "QuickTime"
    if normalized_name == "riff":
        return "RIFF"
    if normalized_name == "xmp":
        return "XMP"
    return None


def canonical_public_output_charset(value: str) -> str:
    normalized_value = value.strip()
    if normalized_value.lower() in {"latin", "latin1", "cp1252"}:
        return "Latin"
    if normalized_value.lower() in {"utf8", "utf-8", "cp65001"}:
        return "UTF8"
    return normalized_value


def parse_required_top_level_option_value(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(missing_top_level_option_value_message(option))
    value = args[value_index]
    if is_if_condition_option(option):
        return value
    if is_file_order_option(option):
        return value
    if is_user_param_option(option):
        return value
    if value.startswith("-"):
        raise argparse.ArgumentTypeError(missing_top_level_option_value_message(option))
    return value


def missing_top_level_option_value_message(option: str) -> str:
    normalized = option.lstrip("-").lower()
    if normalized.startswith("if"):
        return f"Expecting expression for {option} option"
    if normalized.startswith("fileorder"):
        return f"Expecting tag name for {option} option"
    if normalized == "use":
        return "Expecting module name for -use option"
    if normalized == "userparam":
        return "Expected parameter for -userParam option"
    if normalized in {"p", "printformat", "p-", "printformat-"}:
        return f"Expecting print format for {option} option"
    if normalized == "geotag":
        return "Expecting file name for -geotag option"
    return f"Expecting argument for {option} option"


def is_top_level_read_deferred_value_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    body = option.removeprefix("-")
    normalized = body.lower()
    return (
        is_if_condition_option(option)
        or is_file_order_option(option)
        or is_alternate_file_option(option)
        or body == "d"
        or normalized in {"config", "dateformat", "password", "srcfile", "use", "userparam"}
    )


def is_top_level_read_deferred_optional_value_option(option: str) -> bool:
    return False


def is_top_level_read_deferred_flag_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    body = option.removeprefix("-")
    normalized = body.lower()
    if body == "E":
        return True
    if body == "eh":
        return True
    if body == "L":
        return False
    return normalized in {
        "-composite",
        "l",
        "latin",
        "list_dir",
        "h",
        "htmlformat",
        "escapehtml",
        "eh",
        "ec",
        "escapec",
        "ex",
        "escapexml",
    }


def public_read_option_deferred_message(option: str) -> str:
    normalized = option.removeprefix("-").lower()
    if is_if_condition_option(option):
        return (
            "public conditional read filtering for -if is not implemented yet; "
            "the condition parser, referenced-tag request expansion, and per-file "
            "evaluation are not fully represented in the public read path"
        )
    if is_file_order_option(option):
        return (
            "public file ordering for -fileOrder is not implemented yet; "
            "it requires collecting order tags and running an additional extraction pass"
        )
    if is_alternate_file_option(option):
        return (
            "public alternate-file read routing for -fileNUM is not implemented yet; "
            "slot-indexed alternate extraction state is not fully represented"
        )
    if normalized in {"p", "printformat", "p-", "printformat-"}:
        return (
            "public print-format template output for -p/-printFormat is not implemented yet; "
            "template arguments require full ExifTool tag interpolation semantics"
        )
    if normalized == "plot":
        return (
            "public SVG plot output for -plot is not implemented yet; "
            "it is not source-backed because "
            "the public read graph exposes family 0/1/2/4 provenance but no "
            "TAG_EXTRA family-3 document metadata"
        )
    if normalized in {"charset", "lang", "latin"} or option.removeprefix("-") == "L":
        return (
            "public translated/encoded output routing for charset/language options is not "
            "implemented yet; charset, language, and Latin output routing require "
            "shared output-encoding state"
        )
    if normalized in {"d", "dateformat"}:
        return (
            "public DateFormat rendering for -d/-dateFormat is not implemented yet; "
            "date formatting must be applied before extraction/rendering"
        )
    if normalized == "srcfile":
        return (
            "public alternate source-file routing for -srcfile is not implemented yet; "
            "public execution supports @ and ExifTool "
            "FilenameSPrintf-compatible %d/%D/%f/%F/%e/%E forms, but not "
            "InsertTagValues tag interpolation or advanced Perl formatting because "
            "${TAG;EXPR} requires Perl eval semantics"
        )
    if (
        normalized in {"h", "htmlformat", "escapehtml", "eh", "ec", "escapec", "ex", "escapexml"}
        or option.removeprefix("-") == "E"
    ):
        return (
            "public HTML/C/XML escaping output modes are not implemented yet; "
            "the public renderer does not yet own these output encoders"
        )
    if normalized in {"e", "-composite", "ee", "extractembedded"}:
        return (
            "public embedded/composite extraction toggles are not implemented yet; "
            "these options require Image::ExifTool API-option routing parity"
        )
    if normalized == "list_dir":
        return (
            "public directory-listing mode for -list_dir is not implemented yet; "
            "directory-only listing is not represented in the public read renderer"
        )
    if normalized == "use":
        return public_use_deferred_message()
    if normalized == "userparam":
        return (
            "public user-parameter interpolation for -userParam is a release blocker, "
            "not a safe-expression VM route; user parameters affect -if, -p, "
            "-fileNUM, and write redirection expressions"
        )
    if normalized == "config":
        return public_config_deferred_message()
    return (
        f"public read option {option} is recognized from ExifTool but not implemented yet; "
        "the public parser recognizes its argument routing but does not own behavior yet"
    )


def is_if_condition_option(option: str) -> bool:
    body = option.removeprefix("-").lower()
    if body == "if":
        return True
    suffix = body.removeprefix("if")
    return body.startswith("if") and suffix.isdecimal()


def is_file_order_option(option: str) -> bool:
    body = option.removeprefix("-").lower()
    if body == "fileorder":
        return True
    suffix = body.removeprefix("fileorder")
    return body.startswith("fileorder") and suffix.isdecimal()


def is_alternate_file_option(option: str) -> bool:
    return is_public_alternate_file_option(option)


def is_source_file_option(option: str) -> bool:
    return option.removeprefix("-").lower() == "srcfile"


def is_user_param_option(option: str) -> bool:
    return option.removeprefix("-").lower() == "userparam"


def bounded_public_option_suffix(
    option: str,
    prefix: Literal["if", "fileorder"],
) -> int:
    suffix = option.removeprefix("-").lower().removeprefix(prefix)
    return int(suffix) if suffix.isdecimal() else 0


def bounded_alternate_file_slot(option: str) -> int:
    slot = public_bounded_alternate_file_slot(option)
    if slot is None:
        raise argparse.ArgumentTypeError(public_alternate_file_slot_deferred_message(option))
    return slot


def prepare_read_subcommand_double_dash_exclusions(args: Sequence[str]) -> list[str]:
    if not args or args[0] != "read":
        return list(args)

    prepared = ["read"]
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--":
            prepared.extend(args[index:])
            break

        long_option, has_inline_value = read_subcommand_long_option_name(arg)
        if long_option in READ_SUBCOMMAND_DOUBLE_DASH_VALUE_OPTIONS:
            prepared.append(arg)
            index += 1
            if not has_inline_value and index < len(args):
                prepared.append(args[index])
                index += 1
            continue
        if long_option in READ_SUBCOMMAND_DOUBLE_DASH_FLAG_OPTIONS:
            prepared.append(arg)
            index += 1
            continue
        if arg.startswith("--"):
            exclusions: list[str] = []
            append_top_level_read_double_dash_exclusion(exclusions, arg)
            prepared.extend(("-x", exclusions[0]))
            index += 1
            continue

        prepared.append(arg)
        index += 1

    return prepared


def read_subcommand_long_option_name(arg: str) -> tuple[str, bool]:
    option, separator, _value = arg.partition("=")
    return option, separator == "="
