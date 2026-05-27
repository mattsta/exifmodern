"""ExifTool-style public list catalog rendering helpers."""

from __future__ import annotations

import argparse
import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exifmodern.public_api.models import PublicGeolocationListRequest


@dataclass(frozen=True)
class PublicListxTagInfo:
    tag_id: str
    name: str
    value_type: str
    writable: bool
    description: str
    index: int | None = None
    group_0: str | None = None
    group_1: str | None = None
    group_2: str | None = None
    count: str | None = None
    struct: str | None = None
    flags: tuple[str, ...] = ()
    values: tuple[tuple[str, str], ...] = ()
    translated_values: tuple[tuple[str, str, str], ...] = ()
    translated_descriptions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PublicListxTableInfo:
    name: str
    group_0: str
    group_1: str
    group_2: str
    description: str
    tags: tuple[PublicListxTagInfo, ...]
    translated_descriptions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PublicListCatalog:
    available_tags: Sequence[str]
    command_line_shortcuts: Sequence[str]
    writable_tags: Sequence[str]
    supported_extensions: frozenset[str]
    recognized_extensions: frozenset[str]
    writable_extensions: frozenset[str]
    extension_descriptions: Mapping[str, str]
    deletable_groups: Sequence[str]
    groups_by_family: Mapping[int, Sequence[str]]
    listx_tables: Sequence[PublicListxTableInfo]
    group_filter_display_names: Mapping[str, str]
    shortcut_targets: Mapping[str, Sequence[str]]


def is_top_level_list_request(args: Sequence[str]) -> bool:
    return top_level_list_option_index(args) is not None


def top_level_list_option_index(args: Sequence[str]) -> int | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if top_level_list_option_type(arg) is not None:
            return index
        modifier_width = list_output_modifier_width(arg)
        if modifier_width is None:
            return None
        index += modifier_width
    return None


def top_level_list_option_type(option: str) -> str | None:
    if not option.startswith("-"):
        return None
    name = option.removeprefix("-").lower()
    if name in {"list", "listw", "listf", "listr", "listwf", "listd", "listx", "listgeo"}:
        return name.removeprefix("list")
    if name == "listg":
        return "g"
    if name.startswith("listg") and name.removeprefix("listg").isdecimal():
        return f"g{name.removeprefix('listg')}"
    return None


def render_top_level_list(
    args: Sequence[str],
    *,
    catalog: PublicListCatalog,
    quiet_count: int,
    geolocation_package: Path,
) -> str:
    option_index = top_level_list_option_index(args)
    if option_index is None:
        raise argparse.ArgumentTypeError(f"unsupported public list option: {args[0]}")
    list_modifiers = list(args[:option_index])
    list_args = tuple(args[option_index + 1 :])
    post_modifier_count = 0
    while post_modifier_count < len(list_args):
        arg = list_args[post_modifier_count]
        modifier_width = list_output_modifier_width(arg)
        if modifier_width is not None:
            if post_modifier_count + modifier_width > len(list_args):
                raise argparse.ArgumentTypeError(f"Expecting value for {arg} option")
            list_modifiers.extend(
                list_args[post_modifier_count : post_modifier_count + modifier_width]
            )
            post_modifier_count += modifier_width
        else:
            break
    list_args = list_args[post_modifier_count:]
    option_type = top_level_list_option_type(args[option_index])
    if option_type is None:
        raise argparse.ArgumentTypeError(f"unsupported public list option: {args[option_index]}")
    if option_type == "geo":
        return render_top_level_listgeo(
            quiet_count=quiet_count,
            request=geolocation_list_request_from_top_level_args(
                (*list_modifiers, *list_args),
                quiet_count,
                package_path=geolocation_package,
            ),
            geolocation_package=geolocation_package,
        )
    if len(list_args) > 0:
        if option_type == "x":
            return render_public_listx((*list_modifiers, *list_args), catalog=catalog)
        if option_type in {"", "w"} and len(list_args) == 1 and is_list_group_filter(list_args[0]):
            return render_top_level_group_filtered_list(
                option_type,
                list_args[0],
                catalog=catalog,
                quiet_count=quiet_count,
            )
        raise argparse.ArgumentTypeError(
            "public -list* compatibility output does not accept input files yet; "
            "ExifTool list options do not require a file, and group-filtered tag "
            "database lists remain deferred"
        )
    if option_type == "":
        return "".join(
            (
                format_exiftool_list(
                    "Available tags",
                    catalog.available_tags,
                    quiet_count=quiet_count,
                ),
                format_exiftool_list(
                    "Command-line shortcuts",
                    catalog.command_line_shortcuts,
                    details=catalog.shortcut_targets,
                    include_details=has_long_list_output(list_modifiers),
                    quiet_count=quiet_count,
                ),
            )
        )
    if option_type == "w":
        return format_exiftool_list(
            "Writable tags",
            catalog.writable_tags,
            quiet_count=quiet_count,
        )
    if option_type == "f":
        return format_exiftool_file_extension_list(
            "Supported file extensions",
            extensions_without_dot(catalog.supported_extensions),
            descriptions=catalog.extension_descriptions,
            include_descriptions=has_long_list_output(list_modifiers),
            quiet_count=quiet_count,
        )
    if option_type == "r":
        return format_exiftool_file_extension_list(
            "Recognized file extensions",
            extensions_without_dot(catalog.recognized_extensions),
            descriptions=catalog.extension_descriptions,
            include_descriptions=has_long_list_output(list_modifiers),
            quiet_count=quiet_count,
        )
    if option_type == "wf":
        return format_exiftool_file_extension_list(
            "Writable file extensions",
            extensions_without_dot(catalog.writable_extensions),
            descriptions=catalog.extension_descriptions,
            include_descriptions=has_long_list_output(list_modifiers),
            quiet_count=quiet_count,
        )
    if option_type == "d":
        return format_exiftool_list(
            "Deletable groups",
            catalog.deletable_groups,
            quiet_count=quiet_count,
        )
    if option_type == "x":
        return render_public_listx(tuple(list_modifiers), catalog=catalog)
    if option_type == "g" or (option_type.startswith("g") and option_type[1:].isdecimal()):
        family_text = option_type.removeprefix("g")
        family = int(family_text) if family_text else 0
        groups = catalog.groups_by_family.get(family)
        if groups is None:
            raise argparse.ArgumentTypeError(
                "public -listg compatibility is currently bounded to group families 0, 1, and 2"
            )
        return format_exiftool_list(
            f"Groups in family {family}",
            groups,
            quiet_count=quiet_count,
        )
    raise argparse.ArgumentTypeError(
        f"public -list{option_type} tag database output is not implemented yet; "
        "bounded capability lists currently support -listf, -listr, -listwf, "
        "-listg0/-listg1/-listg2, -listd, -list, -listw, and -listgeo without "
        "importing developer tooling"
    )


def render_public_listx(
    args: Sequence[str],
    *,
    catalog: PublicListCatalog,
) -> str:
    short_output = False
    include_flags = False
    language_code = "en"
    group_filter: str | None = None
    group_filter_seen = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-s", "-S", "-short", "-short1", "-short2", "-short3"}:
            short_output = True
            index += 1
            continue
        if arg in {"-f", "-forcePrint", "-forceprint"}:
            include_flags = True
            index += 1
            continue
        if arg.lower() == "-lang":
            value_index = index + 1
            if value_index >= len(args):
                raise argparse.ArgumentTypeError("Expecting language code for -lang option")
            language_code = args[value_index].lower()
            index = value_index + 1
            continue
        parsed_group_filter = list_group_filter_name(arg)
        if parsed_group_filter is not None:
            if group_filter_seen:
                raise argparse.ArgumentTypeError(
                    "public -listx compatibility output accepts only one bounded -GROUP:All filter"
                )
            if is_blocked_canonical_ifd_list_group(parsed_group_filter):
                raise argparse.ArgumentTypeError("Can't list tags for specific IFD")
            group_filter = normalized_public_list_group_filter(parsed_group_filter)
            group_filter_seen = True
            index += 1
            continue
        raise argparse.ArgumentTypeError(
            "public -listx compatibility output accepts only -s, -f, -lang CODE, "
            "and a single bounded -GROUP:All filter for the public tag catalog; "
            "input files remain deferred"
        )
    return format_public_listx(
        short_output=short_output,
        include_flags=include_flags,
        language_code=language_code,
        catalog=catalog,
        group_filter=group_filter,
    )


def is_list_output_modifier(arg: str) -> bool:
    return list_output_modifier_width(arg) is not None


def list_output_modifier_width(arg: str) -> int | None:
    if arg in {"-l", "-long", "-v", "-verbose"}:
        return 1
    if arg in {"-s", "-S", "-short", "-short1", "-short2", "-short3"}:
        return 1
    if arg in {"-f", "-forcePrint", "-forceprint"}:
        return 1
    if arg.lower() == "-lang":
        return 2
    return None


def has_long_list_output(args: Sequence[str]) -> bool:
    return any(arg in {"-l", "-long", "-v", "-verbose"} for arg in args)


def format_public_listx(
    *,
    short_output: bool,
    include_flags: bool,
    language_code: str,
    catalog: PublicListCatalog,
    group_filter: str | None = None,
) -> str:
    lines = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        "<!-- Generated by ExifModern public bounded tag catalog -->",
        "<taginfo>",
        "",
    ]
    for table in catalog.listx_tables:
        if not public_listx_table_matches_group_filter(table, group_filter):
            continue
        tags = tuple(
            tag
            for tag in table.tags
            if public_listx_tag_matches_group_filter(tag, table, group_filter)
        )
        if not tags:
            continue
        lines.append(
            f"<table name='{xml_attr(table.name)}' g0='{xml_attr(table.group_0)}' "
            f"g1='{xml_attr(table.group_1)}' g2='{xml_attr(table.group_2)}'>"
        )
        if not short_output:
            lines.append(f" <desc lang='en'>{xml_text(table.description)}</desc>")
            if language_code and language_code != "en":
                translated_table_description = dict(table.translated_descriptions).get(
                    language_code
                )
                if translated_table_description is not None:
                    lines.append(
                        f" <desc lang='{xml_attr(language_code)}'>"
                        f"{xml_text(translated_table_description)}</desc>"
                    )
        for tag in tags:
            lines.extend(
                format_public_listx_tag(
                    tag,
                    table=table,
                    short_output=short_output,
                    include_flags=include_flags,
                    language_code=language_code,
                )
            )
        lines.append("</table>")
        lines.append("")
    lines.append("</taginfo>")
    return "\n".join(lines) + "\n"


def format_public_listx_tag(
    tag: PublicListxTagInfo,
    *,
    table: PublicListxTableInfo,
    short_output: bool,
    include_flags: bool,
    language_code: str,
) -> list[str]:
    attrs = [
        f"id='{xml_attr(tag.tag_id)}'",
        f"name='{xml_attr(tag.name)}'",
    ]
    if tag.index is not None:
        attrs.append(f"index='{tag.index}'")
    attrs.append(f"type='{xml_attr(tag.value_type)}'")
    if tag.count is not None:
        attrs.append(f"count='{xml_attr(tag.count)}'")
    attrs.append(f"writable='{'true' if tag.writable else 'false'}'")
    if include_flags and tag.flags:
        attrs.append(f"flags='{xml_attr(','.join(sorted(tag.flags)))}'")
    if include_flags and tag.struct is not None:
        attrs.append(f"struct='{xml_attr(tag.struct)}'")
    if tag.group_0 is not None and tag.group_0 != table.group_0:
        attrs.append(f"g0='{xml_attr(tag.group_0)}'")
    if tag.group_1 is not None and tag.group_1 != table.group_1:
        attrs.append(f"g1='{xml_attr(tag.group_1)}'")
    if tag.group_2 is not None and tag.group_2 != table.group_2:
        attrs.append(f"g2='{xml_attr(tag.group_2)}'")
    start_tag = f" <tag {' '.join(attrs)}"
    if short_output:
        return [f"{start_tag}/>"]
    description_language, description = translated_listx_tag_description(tag, language_code)
    lines = [
        f"{start_tag}>",
        f"  <desc lang='{xml_attr(description_language)}'>{xml_text(description)}</desc>",
    ]
    if tag.values:
        lines.append("  <values>")
        for key_id, value in tag.values:
            lines.append(f"   <key id='{xml_attr(key_id)}'>")
            value_language, value_text = translated_listx_tag_value(
                tag,
                key_id,
                value,
                language_code,
            )
            lines.append(f"    <val lang='{xml_attr(value_language)}'>{xml_text(value_text)}</val>")
            lines.append("   </key>")
        lines.append("  </values>")
    lines.append(" </tag>")
    return lines


def translated_listx_tag_description(
    tag: PublicListxTagInfo,
    language_code: str,
) -> tuple[str, str]:
    if not language_code or language_code == "en":
        return "en", tag.description
    translations = dict(tag.translated_descriptions)
    translated = translations.get(language_code)
    if translated is None:
        return "en", tag.description
    return language_code, translated


def translated_listx_tag_value(
    tag: PublicListxTagInfo,
    key_id: str,
    value: str,
    language_code: str,
) -> tuple[str, str]:
    if not language_code or language_code == "en":
        return "en", value
    for translated_key_id, translated_language, translated_value in tag.translated_values:
        if translated_key_id == key_id and translated_language == language_code:
            return translated_language, translated_value
    return "en", value


def public_listx_tag_matches_group_filter(
    tag: PublicListxTagInfo,
    table: PublicListxTableInfo,
    group_filter: str | None,
) -> bool:
    if group_filter is None:
        return True
    groups = {
        (tag.group_0 or table.group_0).lower(),
        (tag.group_1 or table.group_1).lower(),
        (tag.group_2 or table.group_2).lower(),
    }
    return all(group.lower() in groups for group in group_filter.split(":"))


def public_listx_table_matches_group_filter(
    table: PublicListxTableInfo,
    group_filter: str | None,
) -> bool:
    if group_filter is None:
        return True
    groups = {table.group_0.lower(), table.group_1.lower(), table.group_2.lower()}
    if all(group.lower() in groups for group in group_filter.split(":")):
        return True
    if group_filter.lower() not in tag_level_public_list_group_filters():
        return False
    return any(
        public_listx_tag_matches_group_filter(tag, table, group_filter) for tag in table.tags
    )


def render_top_level_group_filtered_list(
    option_type: str,
    group_filter: str,
    *,
    catalog: PublicListCatalog,
    quiet_count: int,
) -> str:
    group_name = list_group_filter_name(group_filter)
    if group_name is None:
        raise argparse.ArgumentTypeError(f"unsupported public list group filter: {group_filter}")
    if option_type == "x":
        return render_public_listx((group_filter,), catalog=catalog)
    if is_blocked_canonical_ifd_list_group(group_name):
        raise argparse.ArgumentTypeError("Can't list tags for specific IFD")
    normalized_group_name = normalized_public_list_group_filter(group_name)
    if normalized_group_name is None:
        if option_type == "w":
            return format_exiftool_list(
                "Writable tags",
                catalog.writable_tags,
                quiet_count=quiet_count,
            )
        return "".join(
            (
                format_exiftool_list(
                    "Available tags",
                    catalog.available_tags,
                    quiet_count=quiet_count,
                ),
                format_exiftool_list(
                    "Command-line shortcuts",
                    catalog.command_line_shortcuts,
                    quiet_count=quiet_count,
                ),
            )
        )
    tags = public_list_tags_for_group_filter(
        normalized_group_name,
        writable_only=option_type == "w",
        catalog=catalog,
    )
    if tags is None:
        raise argparse.ArgumentTypeError(
            f"public -list{option_type} group-filtered output for {group_name} is not "
            "implemented yet; bounded public group catalogs currently cover groups present "
            "in the native public tag catalog, while full ExifTool tag database group "
            "semantics remain deferred"
        )
    list_kind = "Writable" if option_type == "w" else "Available"
    display_name = public_list_group_filter_display_name(normalized_group_name, catalog=catalog)
    return format_exiftool_list(
        f"{list_kind} {display_name} tags",
        tags,
        quiet_count=quiet_count,
    )


def public_list_tags_for_group_filter(
    group_filter: str,
    *,
    writable_only: bool,
    catalog: PublicListCatalog,
) -> tuple[str, ...] | None:
    tags: list[str] = []
    seen: set[str] = set()
    matched_group = False
    for table in catalog.listx_tables:
        for tag in table.tags:
            if not public_listx_tag_matches_group_filter(tag, table, group_filter):
                continue
            matched_group = True
            if writable_only and not public_listw_treats_tag_as_writable(tag, table):
                continue
            if tag.name in seen:
                continue
            tags.append(tag.name)
            seen.add(tag.name)
    return tuple(tags) if matched_group else None


def public_listw_treats_tag_as_writable(
    tag: PublicListxTagInfo,
    table: PublicListxTableInfo,
) -> bool:
    if tag.writable:
        return True
    # ExifTool GetWritableTags can include List-only entries even when
    # TagInfoXML reports the row as not directly writable.
    return (table.name, tag.name) == ("Photoshop::Main", "URL_List")


def public_list_group_filter_display_name(
    group_filter: str,
    *,
    catalog: PublicListCatalog,
) -> str:
    normalized_group = group_filter.lower()
    display_name = catalog.group_filter_display_names.get(normalized_group)
    if display_name is not None:
        return display_name
    return ":".join(
        public_list_group_display_part(part, catalog=catalog) for part in group_filter.split(":")
    )


def public_list_group_display_part(group: str, *, catalog: PublicListCatalog) -> str:
    for table in catalog.listx_tables:
        table_groups = (table.group_0, table.group_1, table.group_2)
        for table_group in table_groups:
            if table_group.lower() == group.lower():
                return table_group
        for tag in table.tags:
            tag_groups = (tag.group_0, tag.group_1, tag.group_2)
            for tag_group in tag_groups:
                if tag_group is not None and tag_group.lower() == group.lower():
                    return tag_group
    return group


def geolocation_list_request_from_top_level_args(
    args: Sequence[str],
    quiet_count: int,
    *,
    package_path: Path,
) -> PublicGeolocationListRequest:
    return public_geolocation_list_request_from_args(
        args,
        package_path=package_path,
        include_title=quiet_count == 0,
    )


def public_geolocation_list_request_from_args(
    args: Sequence[str],
    *,
    package_path: Path,
    include_title: bool,
) -> PublicGeolocationListRequest:
    feature_option = ""
    language_code = ""
    include_alternate_names = False
    sort_by_city = False
    min_population: float | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        lower_arg = arg.lower()
        if lower_arg == "-sort":
            sort_by_city = True
            index += 1
            continue
        if lower_arg == "-lang":
            value_index = index + 1
            if value_index >= len(args):
                raise argparse.ArgumentTypeError("Expecting language code for -lang option")
            language_code = args[value_index]
            index = value_index + 1
            continue
        if lower_arg == "-api":
            value_index = index + 1
            if value_index >= len(args):
                raise argparse.ArgumentTypeError("Expecting NAME=VALUE for -api option")
            option_name, option_value = split_public_api_option(args[value_index])
            normalized_name = option_name.lower()
            if normalized_name == "geolocfeature":
                feature_option = option_value
            elif normalized_name == "geolocminpop":
                min_population = parse_public_api_float(option_name, option_value)
            elif normalized_name == "geolocaltnames":
                include_alternate_names = parse_public_api_bool(option_name, option_value)
            else:
                raise argparse.ArgumentTypeError(
                    "public -listgeo supports ExifTool API options GeolocFeature, "
                    "GeolocMinPop, and GeolocAltNames only"
                )
            index = value_index + 1
            continue
        raise argparse.ArgumentTypeError(
            "public -listgeo accepts only -sort, -lang CODE, and -api "
            "GeolocFeature/GeolocMinPop/GeolocAltNames options"
        )
    request_class = public_geolocation_list_request_class()
    return request_class(
        package_path=package_path,
        language_code=language_code,
        include_alternate_names=include_alternate_names,
        sort_by_city=sort_by_city,
        min_population=min_population,
        feature_option=feature_option,
        include_title=include_title,
    )


def public_geolocation_list_request_from_parts(
    *,
    package_path: Path,
    api_options: tuple[str, ...],
    sort_by_city: bool,
    language_code: str,
    include_title: bool,
) -> PublicGeolocationListRequest:
    option_args: list[str] = []
    if sort_by_city:
        option_args.append("-sort")
    if language_code:
        option_args.extend(("-lang", language_code))
    for api_option in api_options:
        option_args.extend(("-api", api_option))
    return public_geolocation_list_request_from_args(
        option_args,
        package_path=package_path,
        include_title=include_title,
    )


def split_public_api_option(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expecting NAME=VALUE for -api option")
    option_name, option_value = value.split("=", 1)
    if not option_name:
        raise argparse.ArgumentTypeError("Expecting non-empty NAME in -api NAME=VALUE option")
    return option_name, option_value


def parse_public_api_float(option_name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid numeric value for -api {option_name}: {value!r}"
        ) from exc


def parse_public_api_bool(option_name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value for -api {option_name}: {value!r}")


def render_top_level_listgeo(
    *,
    quiet_count: int,
    geolocation_package: Path,
    request: PublicGeolocationListRequest | None = None,
) -> str:
    from exifmodern.public_api.models import list_geolocation

    request_class = public_geolocation_list_request_class()
    list_request = request or request_class(
        package_path=geolocation_package,
        include_title=quiet_count == 0,
    )
    list_result = list_geolocation(list_request)
    if list_result.status != "ok":
        diagnostic = list_result.diagnostics[0] if list_result.diagnostics else None
        message = (
            diagnostic.message
            if diagnostic is not None
            else "public -listgeo could not list the geolocation package"
        )
        raise argparse.ArgumentTypeError(
            f"{message}; run the packaged data generation workflow before using "
            "geolocation list output"
        )
    return list_result.rendered_text


def public_geolocation_list_request_class() -> type[PublicGeolocationListRequest]:
    from exifmodern.public_api.models import PublicGeolocationListRequest

    return PublicGeolocationListRequest


def is_list_group_filter(arg: str) -> bool:
    return list_group_filter_name(arg) is not None


def list_group_filter_name(arg: str) -> str | None:
    if not arg.startswith("-"):
        return None
    parts = arg.removeprefix("-").split(":")
    if len(parts) < 2 or parts[-1].lower() not in {"all", "*"} or not all(parts[:-1]):
        return None
    return ":".join(parts[:-1])


def normalized_public_list_group_filter(group_name: str) -> str | None:
    if group_name.lower() in {"all", "*"}:
        return None
    return group_name


def is_ifd_specific_list_group(group_name: str) -> bool:
    return "ifd" in group_name.lower()


def is_blocked_canonical_ifd_list_group(group_name: str) -> bool:
    return group_name.lower() in {"ifd0", "exififd", "interopifd"}


def tag_level_public_list_group_filters() -> frozenset[str]:
    return frozenset({"ifd1", "ifd2", "subifd", "subifd1", "subifd2"})


def xml_attr(value: str) -> str:
    return html.escape(value, quote=True).replace("'", "&apos;")


def xml_text(value: str) -> str:
    return html.escape(value, quote=False)


def extensions_without_dot(extensions: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(extension.removeprefix(".").upper() for extension in extensions))


def format_exiftool_list(
    title: str,
    values: Sequence[str],
    *,
    details: Mapping[str, Sequence[str]] | None = None,
    include_details: bool = False,
    quiet_count: int,
) -> str:
    lines: list[str] = []
    if quiet_count == 0:
        lines.append(f"{title}:")
    if include_details and details is not None:
        if not values:
            lines.append("  [empty list]")
            return "\n".join(lines) + "\n"
        for value in values:
            detail = ", ".join(details.get(value, ()))
            if detail:
                lines.append(f"  {value:<11} {detail}")
            else:
                lines.append(f"  {value}")
        return "\n".join(lines) + "\n"
    line_length = 0
    pad = "" if quiet_count else "  "
    current_line = ""
    for value in values:
        value_length = len(value)
        if line_length + value_length > 77:
            lines.append(current_line)
            line_length = 0
            pad = "" if quiet_count else "  "
            current_line = ""
        current_line = f"{current_line}{pad}{value}"
        line_length += value_length + 1
        pad = " "
    if not values:
        current_line = f"{current_line}{pad}[empty list]"
    lines.append(current_line)
    return "\n".join(lines) + "\n"


def format_exiftool_file_extension_list(
    title: str,
    values: Sequence[str],
    *,
    descriptions: Mapping[str, str],
    include_descriptions: bool,
    quiet_count: int,
) -> str:
    if not include_descriptions:
        return format_exiftool_list(title, values, quiet_count=quiet_count)

    lines: list[str] = []
    if quiet_count == 0:
        lines.append(f"{title}:")
    if not values:
        lines.append("  [empty list]")
        return "\n".join(lines) + "\n"
    for value in values:
        lines.append(f"  {value:<11} {descriptions.get(value, value)}")
    return "\n".join(lines) + "\n"
