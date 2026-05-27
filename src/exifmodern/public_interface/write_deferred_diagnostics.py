"""Deferred public write option diagnostics for the ExifTool-style CLI."""

from __future__ import annotations


def is_progress_option(arg: str) -> bool:
    if not arg.startswith("-"):
        return False
    option = arg.removeprefix("-").lower()
    return option == "progress" or (
        option.startswith("progress") and option.removeprefix("progress").isdecimal()
    )


def is_execute_option(arg: str) -> bool:
    if not arg.startswith("-"):
        return False
    option = arg.removeprefix("-").lower()
    return option == "execute" or (
        option.startswith("execute") and option.removeprefix("execute").isdecimal()
    )


def public_write_option_deferred_message(option: str) -> str:
    if option == "-P":
        return (
            "public -P/-preserve write filesystem timestamp preservation is not implemented "
            "yet; ExifTool parses -P as preserveTime and later restores file modification "
            "timestamps after successful writes, but MetadataWriteRequest.policy currently "
            "models backup/overwrite behavior only"
        )
    if option == "-o":
        return (
            "public -o/-out write output-file routing executes source-backed "
            "same-file-type rewrite routes, including safe multi-source fanout when "
            "the output route contains ExifTool filename/counter tokens or directory "
            "semantics, plus bounded XMP sidecar creation for .xmp/-.xmp routes "
            "owned by the existing XMP property writer and bounded EXIF sidecar "
            "creation for .exif/-.exif routes owned by the existing EXIF scalar TIFF "
            "materializer. VRD/DR4 selected output can copy exact CanonVRD/CanonDR4 "
            "source blocks through existing CanonVRD block materializers. EXV, MIE, "
            "and ICC/ICM selected creation remains explicitly blocked until native "
            "standalone materializers own those bytes."
        )
    if option == "-w":
        return (
            "public write-context -w/-W external output fanout is not implemented yet; "
            "ExifTool parses -w/-W/-Wext in the shared option parser for per-source "
            "and per-tag output files with overwrite/append and extension filtering, "
            "but public write execution has no safe typed write fanout contract."
        )
    if option == "-b":
        return (
            "public write-context -b/-binary output is not implemented for rewritten "
            "file bytes or external fanout; ExifTool switches to binary stdout/output "
            "mode for extraction, but public write execution does not safely own binary "
            "stdout or unsafe binary fanout."
        )
    if option == "-ee":
        return (
            "public write-context -ee embedded extraction fanout is not implemented; "
            "ExifTool examples combine -ee with -b and -W for embedded binary output, "
            "but public write execution does not safely own embedded binary fanout. "
        )
    if option == "-srcfile":
        return (
            "public -srcfile alternate source-file write routing is not implemented yet; "
            "ExifTool parses -srcfile FMT into source filename templates before file "
            "processing, but MetadataWriteRequest has no typed alternate-source traversal "
            "contract yet."
        )
    if option == "-ext":
        return (
            "public -ext/-extension write file filtering is not implemented yet; ExifTool "
            "parses extension include/exclude filters before directory traversal, but "
            "MetadataWriteRequest has no typed recursive write traversal filter contract "
            "yet."
        )
    if option == "-if":
        return (
            "public conditional write filtering for -if is not implemented yet; ExifTool "
            "parses -if[NUM] expressions, requests referenced tags, and evaluates the "
            "condition per file before writes, but MetadataWriteRequest has no typed "
            "conditional write predicate contract yet."
        )
    if option == "-execute":
        return (
            "public -execute multi-command write batching is not implemented yet; ExifTool "
            "parses command-line sections at -execute[NUM], splits processing there, "
            "and saves write values per command, but the public CLI currently models "
            "one MetadataWriteRequest per invocation."
        )
    if option == "-common_args":
        return (
            "public -common_args write command-sharing is not implemented yet; ExifTool "
            "parses -common_args as arguments shared by all -execute command sections, "
            "but the public CLI currently models one MetadataWriteRequest per invocation. "
        )
    if option == "-wm":
        return (
            "public -wm/-writeMode write creation/replacement policy is not implemented "
            "yet; ExifTool parses -wm MODE into API WriteMode before setting new values, "
            "but MetadataWriteRequest has no typed per-tag write-mode contract yet."
        )
    if option == "-x":
        return (
            "public -x/-exclude write exclusion routing is not implemented yet; ExifTool "
            "parses write-context exclusions into SetNewValue Replace=>2 operations or "
            "tagsFromFile route exclusions, but MetadataWriteRequest has no ordered "
            "exclude/delete/copy route contract yet."
        )
    return (
        "public -progress write progress reporting is not implemented yet; ExifTool parses "
        "-progress as a per-file progress/status side channel, but the public write API "
        "currently returns structured results only after execution"
    )


def public_write_original_maintenance_deferred_message(option: str) -> str:
    if option == "-restore_original":
        return (
            "public -restore_original filesystem original-backup restoration is not "
            "implemented yet; ExifTool restores FILE_original backups by renaming them "
            "over the edited files, but MetadataWriteRequest has no typed original-backup "
            "maintenance operation model yet."
        )
    return (
        "public -delete_original filesystem original-backup deletion is not implemented "
        "yet; ExifTool deletes FILE_original backups as a utility operation separate "
        "from metadata writes, but MetadataWriteRequest has no typed original-backup "
        "maintenance operation model yet."
    )


def public_write_geotag_deferred_message() -> str:
    return (
        "public geotag write planning for -geotag is not implemented yet; "
        "ExifTool parses track files and converts -geotag TRKFILE into a Geotag "
        "write assignment with interpolation through Geotime and GPS tag writes"
    )
