"""Top-level ExifTool-style public write request parsing helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal, Protocol

from exifmodern.public_api import MetadataAssignment, MetadataWriteRequest
from exifmodern.public_api.models import (
    ExifSidecarCopyFromFileRequest,
    ExifSidecarCopyRouteRequest,
    OutputWriteFileRouting,
    PublicCopyFromFileAlternateFile,
    PublicCopyFromFileRequest,
    PublicCopyFromFileRouteRequest,
    PublicImportWriteRequest,
    XmpSidecarCopyFromFileRequest,
    XmpSidecarCopyRouteRequest,
)
from exifmodern.public_interface.alternate_files import (
    alternate_file_format_support,
    resolve_alternate_file_path,
)
from exifmodern.public_interface.output_policy import public_write_output_is_stdout_request
from exifmodern.public_interface.read_options import (
    parse_list_separator_option,
    parse_tag_lookup_package_option,
    parse_top_level_extension_filter,
)
from exifmodern.public_interface.top_level_read_options import (
    is_if_condition_option,
    missing_top_level_option_value_message,
    parse_required_top_level_option_value,
)
from exifmodern.public_interface.write_deferred_diagnostics import (
    is_execute_option,
    is_progress_option,
    public_write_geotag_deferred_message,
    public_write_option_deferred_message,
    public_write_original_maintenance_deferred_message,
)
from exifmodern.services.tag_lookup_runtime import (
    TagLookupRuntimeService,
    TagLookupWriteCapability,
)

type PublicWritePolicy = Literal[
    "preserve_original",
    "overwrite_original",
    "overwrite_original_in_place",
]


class MetadataWriteRequestFromPublicParts(Protocol):
    def __call__(
        self,
        *,
        paths: tuple[Path, ...],
        assignments: tuple[MetadataAssignment, ...],
        deletes: tuple[str, ...],
        delete_order_indexes: tuple[int, ...],
        policy: PublicWritePolicy,
        preserve_file_times: bool = False,
        write_output_file: OutputWriteFileRouting | None = None,
        list_separator: str | None = None,
        tag_lookup_package_path: Path | None = None,
    ) -> MetadataWriteRequest: ...


class PngCopyFromFileRequestParser(Protocol):
    def __call__(
        self,
        *,
        source_file: str,
        routes: tuple[str, ...],
        assignments: tuple[MetadataAssignment, ...],
        deletes: tuple[str, ...],
        paths: tuple[Path, ...],
        policy: PublicWritePolicy,
    ) -> MetadataWriteRequest | None: ...


def parse_top_level_write_request(
    args: Sequence[str],
    *,
    metadata_write_request_from_public_parts: MetadataWriteRequestFromPublicParts,
    png_copy_from_file_request_or_none: PngCopyFromFileRequestParser,
) -> MetadataWriteRequest:
    paths: list[Path] = []
    assignments: list[MetadataAssignment] = []
    deletes: list[str] = []
    delete_order_indexes: list[int] = []
    public_copy_routes: list[PublicCopyFromFileRouteRequest] = []
    public_copy_alternate_files: list[PublicCopyFromFileAlternateFile] = []
    policy: PublicWritePolicy = "preserve_original"
    preserve_file_times = False
    write_output_file: OutputWriteFileRouting | None = None
    list_separator: str | None = None
    tag_lookup_package_path: Path | None = None
    import_write: PublicImportWriteRequest | None = None
    csv_delimiter = ","

    index = 0
    operation_index = 0
    while index < len(args):
        arg = args[index]
        lower_arg = arg.lower()
        if lower_arg in {"-overwrite_original", "-overwriteoriginal"}:
            policy = "overwrite_original"
            if write_output_file is not None:
                write_output_file = _write_output_file_with_policy(write_output_file, policy)
            index += 1
            continue
        if lower_arg == "-overwrite_original_in_place":
            policy = "overwrite_original_in_place"
            if write_output_file is not None:
                write_output_file = _write_output_file_with_policy(write_output_file, policy)
            index += 1
            continue
        if lower_arg in {"-delete_original", "-delete_original!"}:
            raise argparse.ArgumentTypeError(
                public_write_original_maintenance_deferred_message("-delete_original")
            )
        if lower_arg == "-restore_original":
            raise argparse.ArgumentTypeError(
                public_write_original_maintenance_deferred_message("-restore_original")
            )
        if arg == "-P" or lower_arg == "-preserve":
            preserve_file_times = True
            index += 1
            continue
        if lower_arg in {"-o", "-out"}:
            output_path = parse_required_write_output_option_value(arg, args, index)
            write_output_file = _write_output_file_with_policy(
                OutputWriteFileRouting(
                    output_path_template=output_path,
                    stdout=public_write_output_is_stdout_request(output_path),
                ),
                policy,
            )
            index += 2
            continue
        if is_write_context_output_fanout_option(arg):
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-w"))
        if is_write_context_tag_output_extension_filter_option(arg):
            parse_required_write_output_extension_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-w"))
        if lower_arg in {"-b", "-binary"}:
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-b"))
        if lower_arg in {"-ee", "-extractembedded"} or (
            lower_arg.startswith("-ee") and lower_arg.removeprefix("-ee").isdecimal()
        ):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-ee"))
        if lower_arg == "-srcfile":
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-srcfile"))
        if arg in {"-ext", "-extension", "--ext", "--extension", "-ext+", "-extension+"}:
            parse_top_level_extension_filter(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-ext"))
        if is_if_condition_option(arg):
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-if"))
        if is_execute_option(arg):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-execute"))
        if lower_arg == "-common_args":
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-common_args"))
        if is_progress_option(arg):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-progress"))
        if lower_arg in {"-wm", "-writemode"}:
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-wm"))
        if lower_arg in {"-x", "-exclude"}:
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-x"))
        if lower_arg == "-geotag":
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_geotag_deferred_message())
        alternate_slot = public_copy_alternate_file_slot_or_none(arg)
        if alternate_slot is not None:
            alternate_path = Path(parse_required_top_level_option_value(arg, args, index))
            public_copy_alternate_files.append(
                PublicCopyFromFileAlternateFile(
                    raw_option=arg,
                    path=alternate_path,
                    slot=alternate_slot,
                )
            )
            index += 2
            continue
        if lower_arg in {"-sep", "-separator"}:
            list_separator = parse_list_separator_option(arg, args, index)
            index += 2
            continue
        if lower_arg == "-csvdelim":
            csv_delimiter = parse_public_csv_delimiter_option(arg, args, index)
            if import_write is not None and import_write.import_format == "csv":
                import_write = replace(import_write, csv_delimiter=csv_delimiter)
            index += 2
            continue
        if is_csv_json_import_write_option(arg):
            import_write = public_import_write_request_from_option(
                arg,
                csv_delimiter=csv_delimiter,
            )
            index += 1
            continue
        if lower_arg in {"--tag-lookup-package", "--tag-lookup-package-path"}:
            tag_lookup_package_path = parse_tag_lookup_package_option(arg, args, index)
            index += 2
            continue
        if is_tags_from_file_option(arg):
            source_file, route_start_index = parse_tags_from_file_source(args, index, arg)
            return parse_top_level_tags_from_file_write_request(
                args,
                source_file=source_file,
                route_start_index=route_start_index,
                paths_before=tuple(paths),
                assignments_before=tuple(assignments),
                deletes_before=tuple(deletes),
                delete_order_indexes_before=tuple(delete_order_indexes),
                operation_index_start=operation_index,
                policy=policy,
                preserve_file_times=preserve_file_times,
                list_separator=list_separator,
                tag_lookup_package_path=tag_lookup_package_path,
                alternate_files=tuple(public_copy_alternate_files),
                write_output_file=write_output_file,
                png_copy_from_file_request_or_none=png_copy_from_file_request_or_none,
            )
        if arg.startswith("--"):
            raise argparse.ArgumentTypeError(f"unsupported public write option: {arg}")
        if arg.startswith("-"):
            copy_route = public_copy_route_from_direct_write_arg_or_none(
                arg,
                order_index=operation_index,
            )
            if copy_route is not None:
                public_copy_routes.append(copy_route)
                index += 1
                operation_index += 1
                continue
            append_top_level_write_operation(
                assignments,
                deletes,
                arg,
                order_index=operation_index,
                delete_order_indexes=delete_order_indexes,
            )
            index += 1
            operation_index += 1
            continue
        paths.append(Path(arg))
        index += 1

    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")
    if import_write is not None:
        if not paths:
            raise argparse.ArgumentTypeError("at least one file or directory path is required")
        return MetadataWriteRequest(
            paths=tuple(paths),
            assignments=tuple(assignments),
            deletes=tuple(deletes),
            delete_order_indexes=tuple(delete_order_indexes),
            public_copy_from_file=(
                PublicCopyFromFileRequest(
                    source=public_copy_source_for_direct_routes(tuple(public_copy_routes)),
                    source_kind=public_copy_source_kind_for_direct_routes(
                        tuple(public_copy_routes)
                    ),
                    routes=tuple(public_copy_routes),
                    alternate_files=tuple(public_copy_alternate_files),
                )
                if public_copy_routes
                else None
            ),
            import_write=import_write,
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    if public_copy_routes:
        return MetadataWriteRequest(
            paths=tuple(paths),
            assignments=tuple(assignments),
            deletes=tuple(deletes),
            public_copy_from_file=PublicCopyFromFileRequest(
                source=public_copy_source_for_direct_routes(tuple(public_copy_routes)),
                source_kind=public_copy_source_kind_for_direct_routes(tuple(public_copy_routes)),
                routes=tuple(public_copy_routes),
                alternate_files=tuple(public_copy_alternate_files),
            ),
            delete_order_indexes=tuple(delete_order_indexes),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    if not assignments and not deletes:
        raise argparse.ArgumentTypeError("at least one write assignment or delete is required")

    ordered_assignments = (
        tuple(assignments)
        if deletes
        else public_write_assignments_without_order_indexes(tuple(assignments))
    )
    ordered_deletes = tuple(delete_order_indexes) if assignments and deletes else ()
    return metadata_write_request_from_public_parts(
        paths=tuple(paths),
        assignments=ordered_assignments,
        deletes=tuple(deletes),
        delete_order_indexes=ordered_deletes,
        policy=policy,
        preserve_file_times=preserve_file_times,
        write_output_file=write_output_file,
        list_separator=list_separator,
        tag_lookup_package_path=tag_lookup_package_path,
    )


def public_write_assignments_without_order_indexes(
    assignments: tuple[MetadataAssignment, ...],
) -> tuple[MetadataAssignment, ...]:
    return tuple(replace(assignment, order_index=None) for assignment in assignments)


def parse_required_write_output_option_value(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(missing_top_level_option_value_message(option))
    return args[value_index]


def parse_required_write_output_extension_option_value(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError(f"Expecting extension for {option} option")
    return args[value_index]


def is_write_context_output_fanout_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    stripped = option.lstrip("-")
    normalized = stripped.lower()
    return (
        _write_context_option_has_suffix(stripped, "W")
        or _write_context_option_has_suffix(normalized, "w")
        or _write_context_option_has_suffix(normalized, "textout")
        or _write_context_option_has_suffix(normalized, "tagout")
    )


def is_write_context_tag_output_extension_filter_option(option: str) -> bool:
    if not option.startswith("-"):
        return False
    normalized = option.lstrip("-").lower()
    return normalized in {"wext", "tagoutext"}


def _write_context_option_has_suffix(value: str, stem: str) -> bool:
    if not value.startswith(stem):
        return False
    return set(value.removeprefix(stem)) <= {"+", "!"}


def _write_output_file_with_policy(
    routing: OutputWriteFileRouting,
    policy: PublicWritePolicy,
) -> OutputWriteFileRouting:
    return replace(
        routing,
        overwrite_policy="overwrite_existing"
        if policy == "overwrite_original"
        else "error_if_exists",
    )


def parse_top_level_tags_from_file_write_request(
    args: Sequence[str],
    *,
    source_file: str,
    route_start_index: int,
    paths_before: tuple[Path, ...],
    policy: PublicWritePolicy,
    assignments_before: tuple[MetadataAssignment, ...] = (),
    deletes_before: tuple[str, ...] = (),
    delete_order_indexes_before: tuple[int, ...] = (),
    operation_index_start: int = 0,
    preserve_file_times: bool = False,
    list_separator: str | None = None,
    write_output_file: OutputWriteFileRouting | None = None,
    tag_lookup_package_path: Path | None = None,
    png_copy_from_file_request_or_none: PngCopyFromFileRequestParser,
    alternate_files: tuple[PublicCopyFromFileAlternateFile, ...] = (),
) -> MetadataWriteRequest:
    paths = list(paths_before)
    route_tokens: list[str] = []
    public_copy_routes: list[PublicCopyFromFileRouteRequest] = []
    ordered_public_copy_routes: list[PublicCopyFromFileRouteRequest] = []
    public_copy_alternate_files = list(alternate_files)
    assignments: list[MetadataAssignment] = list(assignments_before)
    deletes: list[str] = list(deletes_before)
    delete_order_indexes: list[int] = list(delete_order_indexes_before)
    index = route_start_index
    operation_index = operation_index_start
    while index < len(args):
        arg = args[index]
        lower_arg = arg.lower()
        if lower_arg in {"-overwrite_original", "-overwriteoriginal"}:
            policy = "overwrite_original"
            if write_output_file is not None:
                write_output_file = _write_output_file_with_policy(write_output_file, policy)
            index += 1
            continue
        if lower_arg == "-overwrite_original_in_place":
            policy = "overwrite_original_in_place"
            if write_output_file is not None:
                write_output_file = _write_output_file_with_policy(write_output_file, policy)
            index += 1
            continue
        if lower_arg in {"-delete_original", "-delete_original!"}:
            raise argparse.ArgumentTypeError(
                public_write_original_maintenance_deferred_message("-delete_original")
            )
        if lower_arg == "-restore_original":
            raise argparse.ArgumentTypeError(
                public_write_original_maintenance_deferred_message("-restore_original")
            )
        if arg == "-P" or lower_arg == "-preserve":
            preserve_file_times = True
            index += 1
            continue
        if lower_arg in {"-o", "-out"}:
            output_path = parse_required_write_output_option_value(arg, args, index)
            write_output_file = _write_output_file_with_policy(
                OutputWriteFileRouting(
                    output_path_template=output_path,
                    stdout=public_write_output_is_stdout_request(output_path),
                ),
                policy,
            )
            index += 2
            continue
        if is_write_context_output_fanout_option(arg):
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-w"))
        if is_write_context_tag_output_extension_filter_option(arg):
            parse_required_write_output_extension_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-w"))
        if lower_arg in {"-b", "-binary"}:
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-b"))
        if lower_arg in {"-ee", "-extractembedded"} or (
            lower_arg.startswith("-ee") and lower_arg.removeprefix("-ee").isdecimal()
        ):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-ee"))
        if lower_arg == "-srcfile":
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-srcfile"))
        if arg in {"-ext", "-extension", "--ext", "--extension", "-ext+", "-extension+"}:
            parse_top_level_extension_filter(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-ext"))
        if is_if_condition_option(arg):
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-if"))
        if is_execute_option(arg):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-execute"))
        if lower_arg == "-common_args":
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-common_args"))
        if is_progress_option(arg):
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-progress"))
        if lower_arg in {"-wm", "-writemode"}:
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-wm"))
        if lower_arg in {"-x", "-exclude"}:
            parse_required_top_level_option_value(arg, args, index)
            raise argparse.ArgumentTypeError(public_write_option_deferred_message("-x"))
        if lower_arg in {"-sep", "-separator"}:
            list_separator = parse_list_separator_option(arg, args, index)
            index += 2
            continue
        if is_csv_json_import_write_option(arg):
            raise argparse.ArgumentTypeError(public_csv_json_import_write_deferred_message(arg))
        if lower_arg in {"--tag-lookup-package", "--tag-lookup-package-path"}:
            tag_lookup_package_path = parse_tag_lookup_package_option(arg, args, index)
            index += 2
            continue
        alternate_slot = public_copy_alternate_file_slot_or_none(arg)
        if alternate_slot is not None:
            alternate_path = Path(parse_required_top_level_option_value(arg, args, index))
            public_copy_alternate_files.append(
                PublicCopyFromFileAlternateFile(
                    raw_option=arg,
                    path=alternate_path,
                    slot=alternate_slot,
                )
            )
            index += 2
            continue
        if is_tags_from_file_option(arg):
            next_source_file, next_route_start_index = parse_tags_from_file_source(
                args,
                index,
                arg,
            )
            if next_source_file == source_file:
                index = next_route_start_index
                continue
            raise argparse.ArgumentTypeError(
                tags_from_file_deferred_message(
                    source_file=source_file,
                    routes=tuple(route_tokens) or ("<implicit All copy route>",),
                    implicit_source=False,
                    reason=(
                        "multiple tagsFromFile source files need ordered multi-source "
                        "copy execution; repeated routes from the same source are "
                        "combined by the public parser"
                    ),
                )
            )
        if arg.startswith("--"):
            raise argparse.ArgumentTypeError(f"unsupported public write option: {arg}")
        if arg.startswith("-"):
            if "<" in arg:
                copy_route = public_copy_route_from_direct_write_arg_or_none(
                    arg,
                    order_index=operation_index,
                )
                if copy_route is not None:
                    public_copy_routes.append(copy_route)
                    ordered_public_copy_routes.append(copy_route)
                    index += 1
                    operation_index += 1
                    continue
            if "=" in arg:
                append_top_level_write_operation(
                    assignments,
                    deletes,
                    arg,
                    order_index=operation_index,
                    delete_order_indexes=delete_order_indexes,
                )
                index += 1
                operation_index += 1
            else:
                route_order_index = operation_index
                route_text, index = parse_tags_from_file_route_token(args, index)
                route_tokens.append(route_text)
                ordered_public_copy_routes.append(
                    public_copy_route_from_tags_from_file_route(
                        route_text,
                        order_index=route_order_index,
                    )
                )
                operation_index += 1
            continue
        paths.append(Path(arg))
        index += 1

    png_copy_request = png_copy_from_file_request_or_none(
        source_file=source_file,
        routes=tuple(route_tokens),
        assignments=tuple(assignments),
        deletes=tuple(deletes),
        paths=tuple(paths),
        policy=policy,
    )
    if png_copy_request is not None:
        return replace(
            png_copy_request,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
        )

    if public_copy_routes:
        return MetadataWriteRequest(
            paths=tuple(paths),
            assignments=tuple(assignments),
            deletes=tuple(deletes),
            delete_order_indexes=tuple(delete_order_indexes),
            public_copy_from_file=public_copy_from_tags_from_file_parts(
                source_file=source_file,
                route_tokens=tuple(route_tokens),
                extra_routes=tuple(public_copy_routes),
                preparsed_routes=tuple(ordered_public_copy_routes),
                alternate_files=tuple(public_copy_alternate_files),
            ),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    if assignments or deletes:
        return MetadataWriteRequest(
            paths=tuple(paths),
            assignments=tuple(assignments),
            deletes=tuple(deletes),
            delete_order_indexes=tuple(delete_order_indexes),
            public_copy_from_file=public_copy_from_tags_from_file_parts(
                source_file=source_file,
                route_tokens=tuple(route_tokens),
                extra_routes=tuple(public_copy_routes),
                preparsed_routes=tuple(ordered_public_copy_routes),
                alternate_files=tuple(public_copy_alternate_files),
            ),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    if not route_tokens:
        try:
            implicit_request = parse_implicit_tags_from_file_sidecar_copy_request(
                source_file=source_file,
                paths=tuple(paths),
                policy=policy,
            )
            return replace(
                implicit_request,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
            )
        except argparse.ArgumentTypeError:
            return MetadataWriteRequest(
                paths=tuple(paths),
                public_copy_from_file=public_copy_from_tags_from_file_parts(
                    source_file=source_file,
                    route_tokens=(),
                    extra_routes=tuple(public_copy_routes),
                    preparsed_routes=tuple(ordered_public_copy_routes),
                    alternate_files=tuple(public_copy_alternate_files),
                ),
                policy=policy,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
                tag_lookup_package_path=tag_lookup_package_path,
            )
    if len(route_tokens) != 1:
        redundant_request = parse_redundant_tags_from_file_sidecar_copy_request(
            source_file=source_file,
            route_tokens=tuple(route_tokens),
            paths=tuple(paths),
            policy=policy,
        )
        if redundant_request is not None:
            return replace(
                redundant_request,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
            )
        return MetadataWriteRequest(
            paths=tuple(paths),
            public_copy_from_file=public_copy_from_tags_from_file_parts(
                source_file=source_file,
                route_tokens=tuple(route_tokens),
                extra_routes=tuple(public_copy_routes),
                preparsed_routes=tuple(ordered_public_copy_routes),
                alternate_files=tuple(public_copy_alternate_files),
            ),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    route_text = route_tokens[0]
    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")

    if is_xmp_sidecar_copy_route(route_text):
        if any(path.suffix.lower() != ".xmp" for path in paths):
            return MetadataWriteRequest(
                paths=tuple(paths),
                public_copy_from_file=public_copy_from_tags_from_file_parts(
                    source_file=source_file,
                    route_tokens=(route_text,),
                    extra_routes=tuple(public_copy_routes),
                    preparsed_routes=tuple(ordered_public_copy_routes),
                    alternate_files=tuple(public_copy_alternate_files),
                ),
                policy=policy,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
                tag_lookup_package_path=tag_lookup_package_path,
            )
        try:
            source_path = resolve_tags_from_file_source_path_or_defer(
                source_file=source_file,
                paths=tuple(paths),
                routes=(route_text,),
                sidecar_suffix=".xmp",
            )
            xmp_route = parse_xmp_sidecar_copy_route_or_defer(
                source_file=source_file,
                route=route_text,
            )
        except argparse.ArgumentTypeError:
            return MetadataWriteRequest(
                paths=tuple(paths),
                public_copy_from_file=public_copy_from_tags_from_file_parts(
                    source_file=source_file,
                    route_tokens=(route_text,),
                    extra_routes=tuple(public_copy_routes),
                    preparsed_routes=tuple(ordered_public_copy_routes),
                    alternate_files=tuple(public_copy_alternate_files),
                ),
                policy=policy,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
                tag_lookup_package_path=tag_lookup_package_path,
            )
        return MetadataWriteRequest(
            paths=tuple(paths),
            xmp_sidecar_copy_from_file=XmpSidecarCopyFromFileRequest(
                source_path=source_path,
                routes=(xmp_route,),
            ),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )

    try:
        exif_route = parse_exif_sidecar_copy_route_or_defer(
            source_file=source_file,
            route=route_text,
        )
        if any(path.suffix.lower() != ".exif" for path in paths):
            return MetadataWriteRequest(
                paths=tuple(paths),
                public_copy_from_file=public_copy_from_tags_from_file_parts(
                    source_file=source_file,
                    route_tokens=(route_text,),
                    extra_routes=tuple(public_copy_routes),
                    preparsed_routes=tuple(ordered_public_copy_routes),
                    alternate_files=tuple(public_copy_alternate_files),
                ),
                policy=policy,
                preserve_file_times=preserve_file_times,
                write_output_file=write_output_file,
                list_separator=list_separator,
                tag_lookup_package_path=tag_lookup_package_path,
            )
        source_path = resolve_tags_from_file_source_path_or_defer(
            source_file=source_file,
            paths=tuple(paths),
            routes=(route_text,),
            sidecar_suffix=".exif",
        )
    except argparse.ArgumentTypeError:
        return MetadataWriteRequest(
            paths=tuple(paths),
            public_copy_from_file=public_copy_from_tags_from_file_parts(
                source_file=source_file,
                route_tokens=(route_text,),
                extra_routes=tuple(public_copy_routes),
                preparsed_routes=tuple(ordered_public_copy_routes),
                alternate_files=tuple(public_copy_alternate_files),
            ),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=write_output_file,
            list_separator=list_separator,
            tag_lookup_package_path=tag_lookup_package_path,
        )
    return MetadataWriteRequest(
        paths=tuple(paths),
        exif_sidecar_copy_from_file=ExifSidecarCopyFromFileRequest(
            source_path=source_path,
            routes=(exif_route,),
        ),
        policy=policy,
        preserve_file_times=preserve_file_times,
        write_output_file=write_output_file,
        list_separator=list_separator,
        tag_lookup_package_path=tag_lookup_package_path,
    )


def parse_redundant_tags_from_file_sidecar_copy_request(
    *,
    source_file: str,
    route_tokens: tuple[str, ...],
    paths: tuple[Path, ...],
    policy: PublicWritePolicy,
) -> MetadataWriteRequest | None:
    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")

    xmp_route = redundant_xmp_sidecar_copy_route_or_none(
        source_file=source_file,
        route_tokens=route_tokens,
    )
    if xmp_route is not None:
        source_path = resolve_tags_from_file_source_path_or_defer(
            source_file=source_file,
            paths=paths,
            routes=route_tokens,
            sidecar_suffix=".xmp",
        )
        return MetadataWriteRequest(
            paths=paths,
            xmp_sidecar_copy_from_file=XmpSidecarCopyFromFileRequest(
                source_path=source_path,
                routes=(xmp_route,),
            ),
            policy=policy,
        )

    exif_route = redundant_exif_sidecar_copy_route_or_none(
        source_file=source_file,
        route_tokens=route_tokens,
    )
    if exif_route is not None:
        source_path = resolve_tags_from_file_source_path_or_defer(
            source_file=source_file,
            paths=paths,
            routes=route_tokens,
            sidecar_suffix=".exif",
        )
        return MetadataWriteRequest(
            paths=paths,
            exif_sidecar_copy_from_file=ExifSidecarCopyFromFileRequest(
                source_path=source_path,
                routes=(exif_route,),
            ),
            policy=policy,
        )

    return None


def redundant_xmp_sidecar_copy_route_or_none(
    *,
    source_file: str,
    route_tokens: tuple[str, ...],
) -> XmpSidecarCopyRouteRequest | None:
    if not all(is_xmp_sidecar_copy_route(route) for route in route_tokens):
        return None
    try:
        parsed_routes = tuple(
            parse_xmp_sidecar_copy_route_or_defer(source_file=source_file, route=route)
            for route in route_tokens
        )
    except argparse.ArgumentTypeError:
        return None
    route_keys = {
        (route.source_group, route.destination_group, route.tag_pattern) for route in parsed_routes
    }
    if len(route_keys) != 1:
        return None
    return parsed_routes[0]


def redundant_exif_sidecar_copy_route_or_none(
    *,
    source_file: str,
    route_tokens: tuple[str, ...],
) -> ExifSidecarCopyRouteRequest | None:
    if not all(is_exif_sidecar_copy_route_selector(route) for route in route_tokens):
        return None
    parsed_routes = tuple(
        parse_exif_sidecar_copy_route_or_defer(source_file=source_file, route=route)
        for route in route_tokens
    )
    if {route.source_group for route in parsed_routes} != {"EXIF"}:
        return None
    return parsed_routes[0]


def parse_implicit_tags_from_file_sidecar_copy_request(
    *,
    source_file: str,
    paths: tuple[Path, ...],
    policy: PublicWritePolicy,
) -> MetadataWriteRequest:
    if not paths:
        raise argparse.ArgumentTypeError("at least one file or directory path is required")

    suffixes = {path.suffix.lower() for path in paths}
    if suffixes == {".exif"}:
        source_path = resolve_tags_from_file_source_path_or_defer(
            source_file=source_file,
            paths=paths,
            routes=("<implicit All copy route>",),
            sidecar_suffix=".exif",
        )
        return MetadataWriteRequest(
            paths=paths,
            exif_sidecar_copy_from_file=ExifSidecarCopyFromFileRequest(
                source_path=source_path,
                routes=(ExifSidecarCopyRouteRequest(source_group="EXIF"),),
            ),
            policy=policy,
        )
    if suffixes == {".xmp"}:
        source_path = resolve_tags_from_file_source_path_or_defer(
            source_file=source_file,
            paths=paths,
            routes=("<implicit All copy route>",),
            sidecar_suffix=".xmp",
        )
        return MetadataWriteRequest(
            paths=paths,
            xmp_sidecar_copy_from_file=XmpSidecarCopyFromFileRequest(
                source_path=source_path,
                routes=(
                    XmpSidecarCopyRouteRequest(
                        source_group="ALL",
                        destination_group="ALL",
                    ),
                ),
            ),
            policy=policy,
        )

    raise argparse.ArgumentTypeError(
        tags_from_file_deferred_message(
            source_file=source_file,
            routes=("<implicit All copy route>",),
            implicit_source=False,
            reason=(
                "implicit all-copy routing is supported only for homogeneous .exif "
                "or .xmp sidecar targets"
            ),
        )
    )


def resolve_tags_from_file_source_path_or_defer(
    *,
    source_file: str,
    paths: tuple[Path, ...],
    routes: tuple[str, ...],
    sidecar_suffix: str,
) -> Path:
    if source_file != "@":
        format_support = alternate_file_format_support(source_file)
        if format_support.tag_interpolation:
            raise argparse.ArgumentTypeError(
                tags_from_file_deferred_message(
                    source_file=source_file,
                    routes=routes,
                    implicit_source=False,
                    reason=(
                        "$tag interpolation in -tagsFromFile source filenames is deferred "
                        "until public InsertTagValues-equivalent formatting is connected"
                    ),
                )
            )
        if format_support.filename_percent_codes:
            if len(paths) != 1:
                raise argparse.ArgumentTypeError(
                    tags_from_file_deferred_message(
                        source_file=source_file,
                        routes=routes,
                        implicit_source=False,
                        reason=(
                            "formatted -tagsFromFile source filenames require per-target "
                            "resolution, but this sidecar request shape has one source_path"
                        ),
                    )
                )
            return resolve_alternate_file_path(Path(source_file), paths[0])
        return Path(source_file)
    if len(paths) != 1:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "'@' destination-source copy routing requires a single sidecar target "
                    "because the typed public request has one source_path"
                ),
            )
        )
    target = paths[0]
    if target.suffix.lower() != sidecar_suffix:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=routes,
                implicit_source=False,
                reason=(
                    "'@' destination-source copy routing is supported only when the "
                    f"current target is a {sidecar_suffix} sidecar"
                ),
            )
        )
    return target


def parse_tags_from_file_route_token(args: Sequence[str], index: int) -> tuple[str, int]:
    route = args[index].removeprefix("-")
    redirect_index = index + 1
    destination_index = index + 2
    if (
        ">" not in route
        and redirect_index < len(args)
        and args[redirect_index] == ">"
        and destination_index < len(args)
    ):
        return f"{route} > {args[destination_index]}", destination_index + 1
    return route, index + 1


def reject_unsupported_common_sidecar_copy_route(
    *,
    source_file: str,
    route: str,
) -> None:
    if "<" in route or ">" in route:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="redirected copy syntax is not supported by this bounded sidecar route",
            )
        )


def is_xmp_sidecar_copy_route(route: str) -> bool:
    source_selector, separator, destination_selector = route.partition(">")
    source_group = copy_route_selector_group(source_selector)
    if source_group in {"all", "xmp"}:
        return True
    return bool(separator and copy_route_selector_group(destination_selector) == "xmp")


def copy_route_selector_group(selector: str) -> str:
    group, _separator, _tag_pattern = selector.strip().partition(":")
    return group.lower()


def parse_xmp_sidecar_copy_route_or_defer(
    *,
    source_file: str,
    route: str,
) -> XmpSidecarCopyRouteRequest:
    source_selector, redirect_separator, destination_selector = route.partition(">")
    if redirect_separator:
        source_group, source_tag = parse_bounded_xmp_copy_selector(
            source_selector,
            source_file=source_file,
            route=route,
        )
        destination_group, destination_tag = parse_bounded_xmp_copy_selector(
            destination_selector,
            source_file=source_file,
            route=route,
        )
        if source_tag != "*" or destination_tag != "*":
            raise argparse.ArgumentTypeError(
                tags_from_file_deferred_message(
                    source_file=source_file,
                    routes=(route,),
                    implicit_source=False,
                    reason="only wildcard redirected XMP sidecar routes are supported",
                )
            )
        if source_group == "exif" and destination_group == "xmp":
            return XmpSidecarCopyRouteRequest(
                source_group="EXIF",
                destination_group="XMP",
            )
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="redirected copy syntax is limited to EXIF:* > XMP:*",
            )
        )

    group, separator, tag_pattern = route.partition(":")
    group_name = group.lower()
    if group_name == "all":
        if not separator or tag_pattern.lower() not in {"all", "*"}:
            raise argparse.ArgumentTypeError(
                tags_from_file_deferred_message(
                    source_file=source_file,
                    routes=(route,),
                    implicit_source=False,
                    reason="only All:All or All:* is supported for all-metadata XMP sidecar copy",
                )
            )
        return XmpSidecarCopyRouteRequest(
            source_group="ALL",
            destination_group="ALL",
        )
    if group_name != "xmp":
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="only EXIF and XMP sidecar copy routes are supported by this public slice",
            )
        )
    if separator and tag_pattern.lower() not in {"all", "*"}:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="only XMP, XMP:all, and XMP:* routes are supported",
            )
        )
    return XmpSidecarCopyRouteRequest(
        source_group="XMP",
        destination_group="XMP",
    )


def parse_bounded_xmp_copy_selector(
    selector: str,
    *,
    source_file: str,
    route: str,
) -> tuple[str, str]:
    group, separator, tag_pattern = selector.strip().partition(":")
    group_name = group.lower()
    if separator != ":" or tag_pattern.lower() not in {"all", "*"}:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason=(
                    "redirected XMP sidecar copy requires group wildcard selectors because "
                    "XmpSidecarCopyRouteRequest currently models only tag_pattern='*'"
                ),
            )
        )
    return group_name, "*"


def parse_exif_sidecar_copy_route_or_defer(
    *,
    source_file: str,
    route: str,
) -> ExifSidecarCopyRouteRequest:
    reject_unsupported_common_sidecar_copy_route(source_file=source_file, route=route)
    group, separator, tag_pattern = route.partition(":")
    group_name = group.lower()
    if group_name != "exif":
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="only EXIF and XMP sidecar copy routes are supported by this public slice",
            )
        )
    if separator and tag_pattern.lower() not in {"all", "*"}:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file=source_file,
                routes=(route,),
                implicit_source=False,
                reason="only EXIF, EXIF:all, and EXIF:* routes are supported",
            )
        )
    if not separator:
        return ExifSidecarCopyRouteRequest(source_group="EXIF")
    if tag_pattern.lower() == "*":
        return ExifSidecarCopyRouteRequest(source_group="EXIF", tag_pattern="*")
    return ExifSidecarCopyRouteRequest(source_group="EXIF", tag_pattern="all")


def public_copy_from_tags_from_file_parts(
    *,
    source_file: str,
    route_tokens: tuple[str, ...],
    extra_routes: tuple[PublicCopyFromFileRouteRequest, ...] = (),
    preparsed_routes: tuple[PublicCopyFromFileRouteRequest, ...] | None = None,
    alternate_files: tuple[PublicCopyFromFileAlternateFile, ...] = (),
) -> PublicCopyFromFileRequest:
    routes = route_tokens or ("<implicit All copy route>",)
    if preparsed_routes is None:
        parsed_routes = tuple(
            public_copy_route_from_tags_from_file_route(route, order_index=index)
            for index, route in enumerate(routes)
        )
        request_routes = (*parsed_routes, *extra_routes)
    elif preparsed_routes:
        request_routes = preparsed_routes
    else:
        request_routes = (
            PublicCopyFromFileRouteRequest(
                raw="<implicit All copy route>",
                kind="implicit_all",
                order_index=0,
            ),
        )
    return PublicCopyFromFileRequest(
        source=source_file,
        source_kind="current_target" if source_file == "@" else "explicit_source",
        routes=request_routes,
        alternate_files=alternate_files,
    )


def public_copy_alternate_file_slot_or_none(
    option: str,
) -> Literal[1, 2, 3, 4, 5] | None:
    if not option.startswith("-"):
        return None
    option_name = option.removeprefix("-").lower()
    if not option_name.startswith("file"):
        return None
    slot_text = option_name.removeprefix("file")
    if slot_text == "1":
        return 1
    if slot_text == "2":
        return 2
    if slot_text == "3":
        return 3
    if slot_text == "4":
        return 4
    if slot_text == "5":
        return 5
    return None


def public_copy_route_from_tags_from_file_route(
    route: str,
    *,
    order_index: int,
) -> PublicCopyFromFileRouteRequest:
    if route == "<implicit All copy route>":
        return PublicCopyFromFileRouteRequest(
            raw=route,
            kind="implicit_all",
            order_index=order_index,
        )
    source_selector, separator, destination_selector = route.partition(">")
    if separator:
        return PublicCopyFromFileRouteRequest(
            raw=route,
            kind="redirect_selector",
            order_index=order_index,
            source_selector=source_selector.strip(),
            destination_selector=destination_selector.strip(),
        )
    return PublicCopyFromFileRouteRequest(
        raw=route,
        kind="selector",
        order_index=order_index,
        source_selector=route.strip(),
    )


def public_copy_route_from_direct_write_arg_or_none(
    arg: str,
    *,
    order_index: int,
) -> PublicCopyFromFileRouteRequest | None:
    tag_argument = arg.removeprefix("-")
    if not tag_argument or tag_argument.startswith("-"):
        return None
    if "<=" in tag_argument:
        destination_selector, datfile = tag_argument.split("<=", 1)
        if not destination_selector or not datfile:
            return None
        return PublicCopyFromFileRouteRequest(
            raw=tag_argument,
            kind="datfile_payload",
            order_index=order_index,
            destination_selector=destination_selector,
            datfile_path=Path(datfile),
        )
    if "<" in tag_argument:
        destination_selector, source_selector = tag_argument.split("<", 1)
        if not destination_selector or not source_selector:
            return None
        return PublicCopyFromFileRouteRequest(
            raw=tag_argument,
            kind="redirect_selector",
            order_index=order_index,
            source_selector=source_selector,
            destination_selector=destination_selector,
        )
    if ">" in tag_argument:
        source_selector, destination_selector = tag_argument.split(">", 1)
        if not source_selector or not destination_selector:
            return None
        return PublicCopyFromFileRouteRequest(
            raw=tag_argument,
            kind="redirect_selector",
            order_index=order_index,
            source_selector=source_selector,
            destination_selector=destination_selector,
        )
    return None


def public_copy_source_for_direct_routes(
    routes: tuple[PublicCopyFromFileRouteRequest, ...],
) -> str:
    datfile_routes = tuple(route for route in routes if route.kind == "datfile_payload")
    if len(datfile_routes) == 1 and len(routes) == 1 and datfile_routes[0].datfile_path is not None:
        return datfile_routes[0].datfile_path.as_posix()
    return "@"


def public_copy_source_kind_for_direct_routes(
    routes: tuple[PublicCopyFromFileRouteRequest, ...],
) -> Literal["current_target", "datfile"]:
    if len(routes) == 1 and routes[0].kind == "datfile_payload":
        return "datfile"
    return "current_target"


def append_top_level_write_operation(
    assignments: list[MetadataAssignment],
    deletes: list[str],
    arg: str,
    *,
    order_index: int | None = None,
    delete_order_indexes: list[int] | None = None,
) -> None:
    tag_argument = arg.removeprefix("-")
    if not tag_argument or tag_argument.startswith("-"):
        raise argparse.ArgumentTypeError(f"unsupported public write option: {arg}")
    if "<" in tag_argument or ">" in tag_argument:
        raise argparse.ArgumentTypeError(
            tags_from_file_deferred_message(
                source_file="@",
                routes=(tag_argument,),
                implicit_source=True,
            )
        )
    tag, separator, value = tag_argument.partition("=")
    if separator != "=" or not tag:
        raise argparse.ArgumentTypeError(f"unsupported public write option: {arg}")
    if tag.endswith("+"):
        assignments.append(
            MetadataAssignment(
                tag=tag.removesuffix("+"),
                value=value,
                operation="add_list_value",
                order_index=order_index,
            )
        )
        return
    if tag.endswith("-"):
        assignments.append(
            MetadataAssignment(
                tag=tag.removesuffix("-"),
                value=value,
                operation="delete_list_value",
                order_index=order_index,
            )
        )
        return
    if value == "":
        deletes.append(tag)
        if order_index is not None and delete_order_indexes is not None:
            delete_order_indexes.append(order_index)
        return
    assignments.append(MetadataAssignment(tag=tag, value=value, order_index=order_index))


def public_write_assign_tag_lookup_capabilities(
    service: TagLookupRuntimeService,
    request: MetadataWriteRequest,
) -> tuple[TagLookupWriteCapability, ...]:
    """Classify write-assign/delete TagLookup breadth against owned native routes."""

    target_suffix = public_write_single_target_suffix(request.paths)
    capabilities: list[TagLookupWriteCapability] = []
    for assignment in request.assignments:
        capabilities.append(
            service.write_assignment_capability(
                assignment.tag,
                target_suffix=target_suffix,
            )
        )
    for delete in request.deletes:
        capabilities.append(service.write_delete_capability(delete, target_suffix=target_suffix))
    return tuple(capabilities)


def public_write_single_target_suffix(paths: Sequence[Path]) -> str:
    """Return the only target suffix for route capability checks."""

    suffixes = {path.suffix.lower() for path in paths}
    if len(suffixes) != 1:
        return ""
    return next(iter(suffixes))


def public_list_write_assignment_deferred_message(arg: str) -> str:
    return (
        f"public add/delete list write syntax is unsupported for this route: {arg}; "
        "ExifTool accepts -TAG+=VALUE and -TAG-=VALUE as write operations for adding "
        "or deleting list entries, but this public route does not yet own ordered "
        "list mutation semantics."
    )


def is_csv_json_import_write_option(arg: str) -> bool:
    if not arg.startswith("-") or arg.startswith("--"):
        return False
    option_name, separator, import_path = arg.removeprefix("-").partition("=")
    if not separator or import_path == "":
        return False
    if option_name.endswith("+"):
        option_name = option_name.removesuffix("+")
    return option_name.lower() in {"csv", "j", "json"}


def public_import_write_request_from_option(
    arg: str,
    *,
    csv_delimiter: str = ",",
) -> PublicImportWriteRequest:
    option_name, _separator, import_path = arg.removeprefix("-").partition("=")
    add_list_items = option_name.endswith("+")
    if add_list_items:
        option_name = option_name.removesuffix("+")
    import_format: Literal["csv", "json"] = "csv" if option_name.lower() == "csv" else "json"
    return PublicImportWriteRequest(
        import_format=import_format,
        path=Path(import_path),
        add_list_items=add_list_items,
        csv_delimiter=csv_delimiter,
    )


def parse_public_csv_delimiter_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    delimiter = parse_required_top_level_option_value(option, args, index)
    if '"' in delimiter:
        raise argparse.ArgumentTypeError("CSV delimiter can not contain a double quote")
    unescape = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
    parsed = ""
    position = 0
    while position < len(delimiter):
        char = delimiter[position]
        if char == "\\" and position + 1 < len(delimiter):
            escaped = delimiter[position + 1]
            parsed += unescape.get(escaped, f"\\{escaped}")
            position += 2
            continue
        parsed += char
        position += 1
    if parsed == "":
        raise argparse.ArgumentTypeError("CSV delimiter can not be empty")
    return parsed


def public_csv_json_import_write_deferred_message(arg: str) -> str:
    return (
        f"public CSV/JSON import-write is not implemented for {arg}; ExifTool parses "
        "-csv=FILE, -csv+=FILE, -json=FILE, and -json+=FILE as metadata database "
        "import/write requests, defers them to a second pass so -f/-charset are known, "
        "loads Image::ExifTool::Import::ReadCSV or ReadJSON, then sets writing state. "
        "ExifModern keeps plain -csv/-json read rendering separate from this mutation "
        "path until a bounded import database replay executor owns target matching, "
        "SaveCount ordering, add-vs-replace semantics, and per-target native writer "
        "routing."
    )


def is_tags_from_file_option(arg: str) -> bool:
    if not arg.startswith("-"):
        return False
    option = arg.removeprefix("-")
    option_name, separator, _value = option.partition("=")
    if separator and not option_name:
        return False
    return option_name.lower() in {"tagsfromfile", "addtagsfromfile", "alltagsfromfile"}


def parse_tags_from_file_source(
    args: Sequence[str],
    option_index: int,
    option: str,
) -> tuple[str, int]:
    option_body = option.removeprefix("-")
    _option_name, separator, inline_source = option_body.partition("=")
    if separator:
        if inline_source == "":
            raise argparse.ArgumentTypeError("File must be specified for -tagsFromFile option")
        return inline_source, option_index + 1

    source_index = option_index + 1
    if source_index >= len(args):
        raise argparse.ArgumentTypeError("File must be specified for -tagsFromFile option")
    source_file = args[source_index]
    if source_file == "":
        raise argparse.ArgumentTypeError("File must be specified for -tagsFromFile option")
    return source_file, source_index + 1


def tags_from_file_route_list_deferred_reason(routes: tuple[str, ...]) -> str:
    xmp_routes = tuple(route for route in routes if is_xmp_sidecar_copy_route(route))
    exif_routes = tuple(
        route
        for route in routes
        if route not in xmp_routes and is_exif_sidecar_copy_route_selector(route)
    )
    generic_routes = tuple(
        route for route in routes if route not in xmp_routes and route not in exif_routes
    )
    if generic_routes:
        return (
            "multiple copy routes include generic or unsupported tag-copy selectors; "
            "the bounded public CLI route-list diagnostics apply only to source-backed "
            "EXIF/XMP sidecar copy routes currently modeled by typed requests"
        )
    if xmp_routes and exif_routes:
        return (
            "mixed EXIF/XMP sidecar route lists are source-backed by ExifTool, but "
            "MetadataWriteRequest cannot execute exif_sidecar_copy_from_file and "
            "xmp_sidecar_copy_from_file together without new shared model/executor work"
        )
    if xmp_routes:
        return (
            "multiple XMP sidecar copy routes are source-backed by ExifTool, but "
            "non-equivalent route lists still need ordered XmpCopyFromFilePlan "
            "execution instead of collapsing to one typed route"
        )
    return (
        "multiple EXIF sidecar copy routes are source-backed by ExifTool, but "
        "non-equivalent route lists still need ordered ExifSidecarCopyFromFilePlan "
        "execution instead of collapsing to one typed route"
    )


def is_exif_sidecar_copy_route_selector(route: str) -> bool:
    if "<" in route or ">" in route:
        return False
    return copy_route_selector_group(route) == "exif"


def tags_from_file_deferred_message(
    *,
    source_file: str,
    routes: tuple[str, ...],
    implicit_source: bool,
    reason: str = "general copy-from-file request shape remains deferred",
) -> str:
    source_origin = (
        "ExifTool auto-assumes '-tagsFromFile @' for redirected tag syntax"
        if implicit_source
        else "recognized ExifTool-style -tagsFromFile source"
    )
    return (
        "public tagsFromFile copy-from-file routing is not implemented yet; "
        f"{source_origin}; source={source_file!r}; routes={list(routes)!r}; "
        f"reason={reason}; "
        "supported bounded route is MetadataWriteRequest.exif_sidecar_copy_from_file "
        "for -tagsFromFile SRC -EXIF target.exif, -EXIF:all, and -EXIF:*; "
        "also supported is MetadataWriteRequest.xmp_sidecar_copy_from_file / "
        "XmpSidecarCopyFromFileRequest for -tagsFromFile SRC -XMP target.xmp, "
        "-XMP:all, -XMP:*, -All:All, and '-EXIF:* > XMP:*'; remaining seam is a "
        "general public copy-from-file typed request"
    )


def parse_assignments(
    raw_assignments: Sequence[str],
) -> tuple[tuple[MetadataAssignment, ...], tuple[str, ...]]:
    assignments: list[MetadataAssignment] = []
    deletes: list[str] = []
    for raw_assignment in raw_assignments:
        tag, separator, value = raw_assignment.partition("=")
        if separator != "=" or not tag:
            raise argparse.ArgumentTypeError(
                f"metadata assignment must use TAG=VALUE syntax: {raw_assignment}"
            )
        if tag.endswith("+"):
            assignments.append(
                MetadataAssignment(
                    tag=tag.removesuffix("+"),
                    value=value,
                    operation="add_list_value",
                )
            )
            continue
        if tag.endswith("-"):
            assignments.append(
                MetadataAssignment(
                    tag=tag.removesuffix("-"),
                    value=value,
                    operation="delete_list_value",
                )
            )
            continue
        if value == "":
            deletes.append(tag)
            continue
        assignments.append(MetadataAssignment(tag=tag, value=value))
    return tuple(assignments), tuple(deletes)


def parse_deletes(raw_deletes: Sequence[str]) -> tuple[str, ...]:
    deletes: list[str] = []
    for raw_delete in raw_deletes:
        delete = raw_delete.removesuffix("=")
        if not delete:
            raise argparse.ArgumentTypeError(
                f"metadata delete must name a tag or group: {raw_delete}"
            )
        deletes.append(delete)
    return tuple(deletes)
