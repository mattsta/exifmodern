"""ExifTool-style public read option parsing helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal

from exifmodern.public_api import (
    OutputFileOverwritePolicy,
    OutputFileRoutingRequest,
    OutputPerSourceFileRouting,
    OutputPerTagFileRouting,
    OutputTagFileExtensionFilter,
    OutputWriteFileRouting,
)
from exifmodern.public_api.models import ExtensionFilter, PublicReadTagExclusion

_PUBLIC_READ_SHORTCUT_ALIASES: dict[str, tuple[str, ...]] = {
    "AllDates": ("DateTimeOriginal", "CreateDate", "ModifyDate"),
    "Common": (
        "FileName",
        "FileSize",
        "Model",
        "DateTimeOriginal",
        "ImageSize",
        "Quality",
        "FocalLength",
        "ShutterSpeed",
        "Aperture",
        "ISO",
        "WhiteBalance",
        "Flash",
    ),
    "Canon": (
        "FileName",
        "Model",
        "DateTimeOriginal",
        "ShootingMode",
        "ShutterSpeed",
        "Aperture",
        "MeteringMode",
        "ExposureCompensation",
        "ISO",
        "Lens",
        "FocalLength",
        "ImageSize",
        "Quality",
        "Flash",
        "FlashType",
        "ConditionalFEC",
        "RedEyeReduction",
        "ShutterCurtainHack",
        "WhiteBalance",
        "FocusMode",
        "Contrast",
        "Sharpness",
        "Saturation",
        "ColorTone",
        "ColorSpace",
        "LongExposureNoiseReduction",
        "FileSize",
        "FileNumber",
        "DriveMode",
        "OwnerName",
        "SerialNumber",
    ),
    "Nikon": (
        "Model",
        "SubSecDateTimeOriginal",
        "ShutterCount",
        "LensSpec",
        "FocalLength",
        "ImageSize",
        "ShutterSpeed",
        "Aperture",
        "ISO",
        "NoiseReduction",
        "ExposureProgram",
        "ExposureCompensation",
        "WhiteBalance",
        "WhiteBalanceFineTune",
        "ShootingMode",
        "Quality",
        "MeteringMode",
        "FocusMode",
        "ImageOptimization",
        "ToneComp",
        "ColorHue",
        "ColorSpace",
        "HueAdjustment",
        "Saturation",
        "Sharpness",
        "Flash",
        "FlashMode",
        "FlashExposureComp",
    ),
    "MakerNotes": (
        "MakerNotes",
        "MakerNoteApple",
        "MakerNoteCanon",
        "MakerNoteCasio",
        "MakerNoteCasio2",
        "MakerNoteDJI",
        "MakerNoteDJIInfo",
        "MakerNoteFLIR",
        "MakerNoteFujiFilm",
        "MakerNoteGE",
        "MakerNoteGE2",
        "MakerNoteGoogle",
        "MakerNoteHasselblad",
        "MakerNoteHP",
        "MakerNoteHP2",
        "MakerNoteHP4",
        "MakerNoteHP6",
        "MakerNoteISL",
        "MakerNoteJVC",
        "MakerNoteJVCText",
        "MakerNoteKodak1a",
        "MakerNoteKodak1b",
        "MakerNoteKodak2",
        "MakerNoteKodak3",
        "MakerNoteKodak4",
        "MakerNoteKodak5",
        "MakerNoteKodak6a",
        "MakerNoteKodak6b",
        "MakerNoteKodak7",
        "MakerNoteKodak8a",
        "MakerNoteKodak8b",
        "MakerNoteKodak8c",
        "MakerNoteKodak9",
        "MakerNoteKodak10",
        "MakerNoteKodak11",
        "MakerNoteKodak12",
        "MakerNoteKodakUnknown",
        "MakerNoteKyocera",
        "MakerNoteMinolta",
        "MakerNoteMinolta2",
        "MakerNoteMinolta3",
        "MakerNoteMotorola",
        "MakerNoteNikon",
        "MakerNoteNikon2",
        "MakerNoteNikon3",
        "MakerNoteNintendo",
        "MakerNoteOlympus",
        "MakerNoteOlympus2",
        "MakerNoteOlympus3",
        "MakerNoteLeica",
        "MakerNoteLeica2",
        "MakerNoteLeica3",
        "MakerNoteLeica4",
        "MakerNoteLeica5",
        "MakerNoteLeica6",
        "MakerNoteLeica7",
        "MakerNoteLeica8",
        "MakerNoteLeica9",
        "MakerNoteLeica10",
        "MakerNotePanasonic",
        "MakerNotePanasonic2",
        "MakerNotePanasonic3",
        "MakerNotePentax",
        "MakerNotePentax2",
        "MakerNotePentax3",
        "MakerNotePentax4",
        "MakerNotePentax5",
        "MakerNotePentax6",
        "MakerNotePhaseOne",
        "MakerNoteReconyxHyperFire",
        "MakerNoteReconyxUltraFire",
        "MakerNoteReconyxHyperFire2",
        "MakerNoteReconyxMicroFire",
        "MakerNoteReconyxHyperFire4K",
        "MakerNoteRicohPentax",
        "MakerNoteRicoh",
        "MakerNoteRicoh2",
        "MakerNoteRicohText",
        "MakerNoteSamsung1a",
        "MakerNoteSamsung1b",
        "MakerNoteSamsung2",
        "MakerNoteSanyo",
        "MakerNoteSanyoC4",
        "MakerNoteSanyoPatch",
        "MakerNoteSigma",
        "MakerNoteSony",
        "MakerNoteSony2",
        "MakerNoteSony3",
        "MakerNoteSony4",
        "MakerNoteSony5",
        "MakerNoteSonyEricsson",
        "MakerNoteSonySRF",
        "MakerNoteUnknownText",
        "MakerNoteUnknownBinary",
        "MakerNoteUnknown",
    ),
    "Unsafe": (
        "IFD0:YCbCrPositioning",
        "IFD0:YCbCrCoefficients",
        "IFD0:TransferFunction",
        "ExifIFD:ComponentsConfiguration",
        "ExifIFD:CompressedBitsPerPixel",
        "InteropIFD:InteropIndex",
        "InteropIFD:InteropVersion",
        "InteropIFD:RelatedImageWidth",
        "InteropIFD:RelatedImageHeight",
    ),
    "ColorSpaceTags": (
        "ExifIFD:ColorSpace",
        "ExifIFD:Gamma",
        "InteropIFD:InteropIndex",
        "ICC_Profile",
    ),
    "CommonIFD0": (
        "IFD0:ImageDescription",
        "IFD0:Make",
        "IFD0:Model",
        "IFD0:Software",
        "IFD0:ModifyDate",
        "IFD0:Artist",
        "IFD0:Copyright",
        "IFD0:Rating",
        "IFD0:RatingPercent",
        "IFD0:DNGLensInfo",
        "IFD0:PanasonicTitle",
        "IFD0:PanasonicTitle2",
        "IFD0:XPTitle",
        "IFD0:XPComment",
        "IFD0:XPAuthor",
        "IFD0:XPKeywords",
        "IFD0:XPSubject",
    ),
    "LargeTags": (
        "CanonVRD",
        "DLOData",
        "EXIF",
        "ICC_Profile",
        "IDCPreviewImage",
        "ImageData",
        "IPTC",
        "JpgFromRaw",
        "OriginalRawImage",
        "OtherImage",
        "PreviewImage",
        "ThumbnailImage",
        "TIFFPreview",
        "XML",
        "XMP",
        "ZoomedPreviewImage",
    ),
    "ls-l": (
        "FilePermissions",
        "FileHardLinks",
        "FileUserID",
        "FileGroupID",
        "FileSize#",
        "FileModifyDate",
        "FileName",
    ),
    "ImageDataMD5": ("ImageDataHash",),
}

_PUBLIC_READ_SHORTCUT_ALIASES_BY_LOWER = {
    shortcut.lower(): shortcut for shortcut in _PUBLIC_READ_SHORTCUT_ALIASES
}
_PUBLIC_READ_TAG_OUTPUT_NAME_ALIASES: dict[str, str] = {
    "exiftoolversionnumber": "ExifToolVersion",
    "fileaccessdatetime": "FileAccessDate",
    "filecreationdatetime": "FileCreateDate",
    "filemodificationdatetime": "FileModifyDate",
}


class ExtensionFilterAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None or not isinstance(values, str):
            parser.error("internal extension filter parser error")
        filters = list(getattr(namespace, self.dest, None) or [])
        filters.append(extension_filter_from_option(option_string, values))
        setattr(namespace, self.dest, filters)


class OutputFileRoutingAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None or not isinstance(values, str):
            parser.error("internal output routing parser error")
        routing = getattr(namespace, self.dest, None)
        if not isinstance(routing, OutputFileRoutingRequest):
            routing = OutputFileRoutingRequest()
        setattr(
            namespace,
            self.dest,
            output_file_routing_with_option(routing, option_string, values),
        )


class PublicReadTagAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if option_string is None or not isinstance(values, str):
            parser.error("internal public read tag parser error")
        tags = list(getattr(namespace, self.dest, None) or [])
        try:
            append_public_read_tag(tags, values, option=option_string)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        setattr(namespace, self.dest, tags)


def group_name_families_from_argparse(
    args: argparse.Namespace,
) -> tuple[Literal[0, 1, 2, 4], ...]:
    families: list[Literal[0, 1, 2, 4]] = []
    families.extend(args.group_name_families)
    for chain in args.group_name_family_chains:
        families.extend(chain)
    return tuple(families)


def parse_fast_scan_option(option: str) -> int | None:
    if not option.startswith("-fast"):
        return None
    suffix = option.removeprefix("-fast")
    if suffix == "":
        return 1
    if suffix.isdecimal():
        return int(suffix)
    return None


def parse_ignore_directory_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting directory name for {option} option")
    return args[value_index]


def parse_read_exclusion_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting tag name for {option} option")
    value = args[value_index]
    if not value or value.startswith("-"):
        raise argparse.ArgumentTypeError(f"Expecting tag name for {option} option")
    return normalize_public_read_exclusion(value)


def append_top_level_read_double_dash_exclusion(exclusions: list[str], arg: str) -> None:
    tag = arg.removeprefix("--")
    if not tag or tag.startswith("-"):
        raise argparse.ArgumentTypeError(f"unsupported public read option: {arg}")
    if any(marker in tag for marker in ("=", "<", ">")):
        raise argparse.ArgumentTypeError(
            f"public write-style tag syntax is not implemented yet: {arg}"
        )
    exclusions.append(normalize_public_read_exclusion(tag))


def public_read_tag_exclusions_from_raw(
    raw_exclusions: Sequence[str],
) -> tuple[PublicReadTagExclusion, ...]:
    return tuple(
        PublicReadTagExclusion(raw=expanded)
        for raw in raw_exclusions
        for expanded in expand_public_read_shortcuts(
            normalize_public_read_exclusion(raw),
            remove_value_suffix=True,
            skip_excluded_targets=True,
        )
    )


def normalize_public_read_exclusion(raw: str) -> str:
    return ":".join("*" if part.lower() == "all" else part for part in raw.split(":"))


def public_read_tags_from_raw(raw_tags: Sequence[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for raw in raw_tags:
        append_public_read_tag(tags, raw)
    return tuple(tags)


def public_read_shortcut_names() -> tuple[str, ...]:
    """Return ExifTool built-in command-line shortcut names in GetShortcuts order."""
    return tuple(sorted(_PUBLIC_READ_SHORTCUT_ALIASES, key=str.casefold))


def public_read_shortcut_targets(shortcut_name: str) -> tuple[str, ...] | None:
    canonical = _PUBLIC_READ_SHORTCUT_ALIASES_BY_LOWER.get(shortcut_name.lower())
    if canonical is None:
        return None
    return _PUBLIC_READ_SHORTCUT_ALIASES[canonical]


def append_public_read_tag(
    tags: list[str],
    raw: str,
    *,
    option: str = "--tag",
) -> None:
    if not raw or raw.startswith("-"):
        raise argparse.ArgumentTypeError(f"Expecting tag name for {option} option")
    if any(marker in raw for marker in ("=", "<", ">")):
        raise argparse.ArgumentTypeError(
            f"public write-style tag syntax is not implemented yet: {raw}"
        )
    if raw.lower() in {"all", "*"}:
        tags.clear()
        return
    tags.extend(expand_public_read_shortcuts(raw))


def expand_public_read_shortcuts(
    raw: str,
    *,
    remove_value_suffix: bool = False,
    skip_excluded_targets: bool = False,
) -> tuple[str, ...]:
    prefix, tag = _split_public_shortcut_group_prefix(raw)
    tag_name, value_suffix = _split_public_shortcut_value_suffix(
        tag,
        remove_value_suffix=remove_value_suffix,
    )
    shortcut_name = _PUBLIC_READ_SHORTCUT_ALIASES_BY_LOWER.get(tag_name.lower())
    if shortcut_name is None:
        return (f"{prefix}{_public_read_output_name_alias(tag_name)}{value_suffix}",)
    targets: list[str] = []
    for target in _PUBLIC_READ_SHORTCUT_ALIASES[shortcut_name]:
        if skip_excluded_targets and target.startswith("-"):
            continue
        target_prefix, target_name = _split_public_shortcut_group_prefix(target)
        if target_prefix:
            targets.append(f"{target_prefix}{target_name}{value_suffix}")
        else:
            targets.append(f"{prefix}{target_name}{value_suffix}")
    return tuple(targets)


def _public_read_output_name_alias(tag_name: str) -> str:
    return _PUBLIC_READ_TAG_OUTPUT_NAME_ALIASES.get(
        _normalized_public_read_output_name_alias(tag_name),
        tag_name,
    )


def _normalized_public_read_output_name_alias(tag_name: str) -> str:
    return "".join(character for character in tag_name.lower() if character.isalnum())


def _split_public_shortcut_group_prefix(raw: str) -> tuple[str, str]:
    if ":" not in raw:
        return "", raw
    prefix, tag = raw.rsplit(":", 1)
    return f"{prefix}:", tag


def _split_public_shortcut_value_suffix(
    raw: str,
    *,
    remove_value_suffix: bool,
) -> tuple[str, str]:
    if not raw.endswith("#"):
        return raw, ""
    return raw.removesuffix("#"), "" if remove_value_suffix else "#"


def parse_group_name_families_option(
    option: str,
) -> tuple[Literal[0, 1, 2, 4], ...] | None:
    if option == "-G" or option.lower() == "-groupnames":
        return ()
    if not option.startswith("-G") or option == "-G":
        return None

    family_spec = option.removeprefix("-G")
    if family_spec[0] not in "0124:":
        return None
    if not family_spec:
        return ()
    families: list[Literal[0, 1, 2, 4]] = []
    for family in family_spec.split(":"):
        if family == "":
            continue
        if family not in {"0", "1", "2", "4"}:
            raise argparse.ArgumentTypeError(
                f"unsupported public output group family in {option}: {family}"
            )
        families.append(_group_name_family_from_digit(family))
    return tuple(families)


def _group_name_family_from_digit(digit: str) -> Literal[0, 1, 2, 4]:
    if digit == "0":
        return 0
    if digit == "2":
        return 2
    if digit == "4":
        return 4
    return 1


def parse_top_level_extension_filter(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> ExtensionFilter:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting extension for {option} option")
    return extension_filter_from_option(option, args[value_index])


def extension_filter_from_option(option: str, value: str) -> ExtensionFilter:
    if option in {"--ext", "--extension"}:
        return ExtensionFilter(extension=value, mode="exclude")
    if option in {"-ext+", "-extension+"}:
        return ExtensionFilter(extension=value, mode="include_extra")
    return ExtensionFilter(extension=value, mode="include")


def is_output_file_routing_option(option: str) -> bool:
    stripped = option.lstrip("-")
    normalized = stripped.lower()
    if normalized in {"o", "out", "wext", "tagoutext"}:
        return True
    if stripped.startswith("W") and set(stripped.removeprefix("W")) <= {"+", "!"}:
        return True
    return (
        _has_output_option_suffix(stripped, "w")
        or _has_output_option_suffix(
            normalized,
            "textout",
        )
        or _has_output_option_suffix(normalized, "tagout")
    )


def _has_output_option_suffix(value: str, stem: str) -> bool:
    if not value.startswith(stem):
        return False
    return set(value.removeprefix(stem)) <= {"+", "!"}


def parse_output_file_routing_value_option(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> str:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting argument for {option} option")
    return args[value_index]


def output_file_routing_with_option(
    routing: OutputFileRoutingRequest,
    option: str,
    value: str,
) -> OutputFileRoutingRequest:
    normalized = option.lstrip("-").lower()
    if normalized.startswith(("wext", "tagoutext")):
        return _output_file_routing_with_tag_extension_filter(routing, option, value)
    if normalized in {"o", "out"}:
        return replace(
            routing,
            write_output_file=OutputWriteFileRouting(
                output_path_template=value,
                stdout=value == "-",
            ),
        )
    if normalized.startswith("tagout") or _is_uppercase_tag_output_option(option):
        return replace(
            routing,
            per_tag_file=OutputPerTagFileRouting(
                format_template=value,
                overwrite_policy=_output_overwrite_policy_from_option(option),
                extension_filters=(
                    () if routing.per_tag_file is None else routing.per_tag_file.extension_filters
                ),
            ),
        )
    return replace(
        routing,
        per_source_file=OutputPerSourceFileRouting(
            format_template=value,
            overwrite_policy=_output_overwrite_policy_from_option(option),
        ),
    )


def _output_file_routing_with_tag_extension_filter(
    routing: OutputFileRoutingRequest,
    option: str,
    value: str,
) -> OutputFileRoutingRequest:
    current = routing.per_tag_file
    extension_filter = OutputTagFileExtensionFilter(
        extension=value.removeprefix(".").lower(),
        mode="exclude" if option.startswith("--") else "include",
    )
    if current is None:
        current = OutputPerTagFileRouting(
            format_template="",
            extension_filters=(extension_filter,),
        )
    else:
        current = replace(
            current,
            extension_filters=(*current.extension_filters, extension_filter),
        )
    return replace(routing, per_tag_file=current)


def _is_uppercase_tag_output_option(option: str) -> bool:
    stripped = option.lstrip("-")
    return stripped.startswith("W") and not stripped.lower().startswith("wext")


def _output_overwrite_policy_from_option(option: str) -> OutputFileOverwritePolicy:
    if "+" in option and "!" in option:
        return "overwrite_new_then_append"
    if "+" in option:
        return "append_existing"
    if "!" in option:
        return "overwrite_existing"
    return "error_if_exists"


def parse_csv_delimiter_option(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> str:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting argument for {option} option")
    return parse_csv_delimiter(args[value_index])


def parse_list_separator_option(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> str:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting list item separator for {option} option")
    return parse_exiftool_escaped_text(args[value_index])


def parse_tag_lookup_package_option(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> Path:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting generated-index package path for {option}")
    return Path(args[value_index])


def parse_list_item_option(
    option: str,
    args: Sequence[str],
    option_index: int,
) -> int:
    value_index = option_index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting integer for {option} option")
    try:
        return int(args[value_index])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expecting integer for {option} option") from exc


def parse_csv_delimiter(value: str) -> str:
    if '"' in value:
        raise argparse.ArgumentTypeError("CSV delimiter can not contain a double quote")
    return parse_exiftool_escaped_text(value)


def parse_exiftool_escaped_text(value: str) -> str:
    unescaped: list[str] = []
    index = 0
    escapes = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            unescaped.append(escapes.get(escaped, f"\\{escaped}"))
            index += 2
            continue
        unescaped.append(character)
        index += 1
    return "".join(unescaped)


def append_top_level_read_tag(tags: list[str], arg: str) -> None:
    tag = arg.removeprefix("-")
    if not tag or tag.startswith("-"):
        raise argparse.ArgumentTypeError(f"unsupported public read option: {arg}")
    if len(tag) == 1 and tag != "*":
        raise argparse.ArgumentTypeError(f"Unknown option {arg}")
    append_public_read_tag(tags, tag, option=arg)
