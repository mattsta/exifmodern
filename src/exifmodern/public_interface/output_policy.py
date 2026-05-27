"""ExifTool-compatible public output suppression policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.json_types import JsonObject
from exifmodern.provenance.public_interface import public_evidence_values

if TYPE_CHECKING:
    from exifmodern.public_api.models import MetadataReadResult
    from exifmodern.read_graph import ReadGraph, ReadTag


class _PublicEvidenceIdsMixin:
    evidence_ids: tuple[str, ...]


type PublicReadStdoutAction = Literal[
    "emit_binary",
    "emit_text",
    "emit_json",
    "suppress",
]
type PublicReadStdoutSuppressionReason = Literal[
    "external_output_file_routing",
    "condition_failed_without_records",
]
type PublicOutputSuppressionReason = Literal[
    "exiftool_dynamic_unknown_tag",
    "exiftool_unknown_makernote",
    "exiftool_unknown_matroska",
    "exiftool_internal_exe_planner",
    "exiftool_macos_sidecar_container",
]
type PublicWriteOutputRouteBlocker = Literal[
    "overwrite_original_in_place_with_output_file",
    "stdout_write_output_routing",
    "write_output_filename_template",
    "multi_source_write_output_routing",
    "write_output_to_source_path",
    "duplicate_write_output_file_route",
    "existing_write_output_file_without_overwrite",
    "write_output_file_type_conversion",
    "write_output_zero_length_path",
]
type PublicWriteOutputOverwritePolicy = Literal[
    "error_if_exists",
    "overwrite_existing",
    "append_existing",
    "overwrite_new_then_append",
]
type PublicWriteOutputPolicy = Literal[
    "preserve_original",
    "overwrite_original",
    "overwrite_original_in_place",
]
type PublicSelectedOutputMaterializerDecision = Literal["implemented", "terminal_blocked"]

_APPLE_DYNAMIC_UNKNOWN_TAG_RE = re.compile(r"^Apple_0x[0-9a-fA-F]{4}$")
_TIFF_DYNAMIC_UNKNOWN_TAG_RE = re.compile(r"^(?:Exif|GPS)_0x[0-9a-fA-F]{4}$")
_APPLE_DECLARED_UNKNOWN_TAGS = frozenset(
    {
        "AEMatrix",
        "ColorCorrectionMatrix",
        "GreenGhostMitigationStatus",
        "ImageCaptureRequestID",
        "ImageProcessingFlags",
        "QualityHint",
        "SceneFlags",
        "SignalToNoiseRatioType",
    }
)
_MATROSKA_DECLARED_UNKNOWN_TAGS = frozenset(
    {
        "AttachedFileReferral",
        "Block",
        "BlockAddID",
        "BlockAdditional",
        "BlockAdditionalID",
        "BlockDuration",
        "BlockVirtual",
        "CRC-32",
        "ChannelPositions",
        "ChapterFlagEnabled",
        "ChapterFlagHidden",
        "ChapterProcessCodecID",
        "ChapterProcessData",
        "ChapterProcessPrivate",
        "ChapterProcessTime",
        "ChapterSegmentEditionUID",
        "ChapterSegmentUID",
        "ChapterTrackNumber",
        "ChapterTranslateEditionUID",
        "ChapterTranslateID",
        "ChapterUID",
        "ClusterDuration",
        "CodecPrivate",
        "CodecState",
        "ColorSpace",
        "ContentCompressionSettings",
        "ContentEncodingOrder",
        "ContentEncodingScope",
        "ContentEncryptionKeyID",
        "ContentSignature",
        "ContentSignatureKeyID",
        "CueBlockNumber",
        "CueClusterPosition",
        "CueCodecState",
        "CueRefCluster",
        "CueRefCodecState",
        "CueRefNumber",
        "CueRefTime",
        "CueTime",
        "CueTrack",
        "Delay",
        "EBMLMaxIDLength",
        "EBMLMaxSizeLength",
        "EditionFlagDefault",
        "EditionFlagHidden",
        "EditionFlagOrdered",
        "EditionUID",
        "EncryptedBlock",
        "FrameNumber",
        "LaceNumber",
        "MaxBlockAdditionID",
        "MaxCache",
        "MinCache",
        "NextUID",
        "PrevUID",
        "ReferenceBlock",
        "ReferencePriority",
        "ReferenceVirtual",
        "SeekID",
        "SeekPosition",
        "SegmentFamily",
        "SegmentUID",
        "Signature",
        "SignaturePublicKey",
        "SignedElement",
        "SimpleBlock",
        "TimeCode",
        "TrackLacing",
        "TrackOffset",
        "TrackOverlay",
        "TrackTranslateEditionUID",
        "TrackTranslateTrackID",
        "Void",
    }
)
_EXIFTOOL_FILENAME_SPRINTF_TOKEN_RE = re.compile(r"%[-+]?\d*[.:]?\d*[lu]?[dDfFeEtgso]")
_EXIFTOOL_COPY_COUNTER_TOKEN_RE = re.compile(r"%[-+]?\d*[.:]?\d*[lun]?[cC]")
_EXIFTOOL_FILENAME_SPRINTF_EXPAND_RE = re.compile(r"%([-+]?)(\d*)([.:]?)(\d*)([lu]?)([dDfFeEtgso])")
_EXIFTOOL_COPY_COUNTER_EXPAND_RE = re.compile(r"%([-+]?)(\d*)([.:]?)(\d*)([lun]?)([cC])")
_WRITE_OUTPUT_STDOUT_RE = re.compile(r"^-(?:\.\w+)?$")
_WRITE_OUTPUT_STDOUT_EXTENSION_RE = re.compile(r"^-(?P<extension>\.\w+)$")
_OUTPUT_FILE_TYPE_SUFFIX_GROUPS = (
    frozenset({".jpg", ".jpeg", ".jpe"}),
    frozenset({".tif", ".tiff"}),
    frozenset({".icc", ".icm"}),
)
_PUBLIC_CREATABLE_WRITE_OUTPUT_SUFFIXES = frozenset(
    {".dr4", ".exif", ".exv", ".icc", ".icm", ".mie", ".vrd", ".xmp"}
)


@dataclass(frozen=True)
class _FilenameSprintfParts:
    directory: str
    directory_no_trailing_slash: str
    filename_stem: str
    extension: str
    extension_with_dot: str
    filename: str


@dataclass(frozen=True)
class PublicFilenameSprintfTagContext:
    tag_name: str = ""
    group_names: tuple[str, ...] = ()
    suggested_extension: str = ""
    original_file_name: str = ""


@dataclass(frozen=True)
class PublicOutputSuppression(_PublicEvidenceIdsMixin):
    reason: PublicOutputSuppressionReason
    evidence_ids: tuple[str, ...]

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {"reason": self.reason}
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicWriteOutputPolicyDecision(_PublicEvidenceIdsMixin):
    blocker: PublicWriteOutputRouteBlocker | None
    unsupported_value: str | None
    message: str
    evidence_ids: tuple[str, ...]
    source_path: Path | None = None
    output_path: Path | None = None

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "blocker": self.blocker,
            "unsupported_value": self.unsupported_value,
            "message": self.message,
            "source_path": self.source_path.as_posix() if self.source_path is not None else None,
            "output_path": self.output_path.as_posix() if self.output_path is not None else None,
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicReadStdoutDecision(_PublicEvidenceIdsMixin):
    action: PublicReadStdoutAction
    suppression_reason: PublicReadStdoutSuppressionReason | None
    message: str
    evidence_ids: tuple[str, ...]

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "action": self.action,
            "suppression_reason": self.suppression_reason,
            "message": self.message,
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicSelectedOutputMaterializerContract(_PublicEvidenceIdsMixin):
    selected_output_type: str
    decision: PublicSelectedOutputMaterializerDecision
    reason: str
    message: str
    evidence_ids: tuple[str, ...]
    owned_primitives_checked: tuple[str, ...]
    insufficient_primitives: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    terminal_contract_artifact: str

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "selected_output_type": self.selected_output_type,
            "decision": self.decision,
            "reason": self.reason,
            "message": self.message,
            "owned_primitives_checked": list(self.owned_primitives_checked),
            "insufficient_primitives": list(self.insufficient_primitives),
            "required_dependencies": list(self.required_dependencies),
            "terminal_contract_artifact": self.terminal_contract_artifact,
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


def classify_public_read_stdout_route(read_result: MetadataReadResult) -> PublicReadStdoutDecision:
    evidence_ids = public_read_stdout_evidence_ids()
    if read_result.output_files and read_result.status == "ok":
        return PublicReadStdoutDecision(
            action="suppress",
            suppression_reason="external_output_file_routing",
            message=(
                "ExifTool external read-output routing writes console payloads to "
                "the requested files instead of also emitting the same payloads to stdout."
            ),
            evidence_ids=evidence_ids,
        )
    if read_result.status == "condition_failed" and not read_result.records:
        return PublicReadStdoutDecision(
            action="suppress",
            suppression_reason="condition_failed_without_records",
            message=(
                "ExifTool -if failures do not emit record output for files that failed "
                "the condition."
            ),
            evidence_ids=evidence_ids,
        )
    if (
        read_result.status == "ok"
        and read_result.request.render.binary_output
        and read_result.rendered_binary
    ):
        return PublicReadStdoutDecision(
            action="emit_binary",
            suppression_reason=None,
            message=(
                "ExifTool -b emits the requested metadata value bytes directly to stdout "
                "when no external output file route is active."
            ),
            evidence_ids=evidence_ids,
        )
    if read_result.rendered_text:
        return PublicReadStdoutDecision(
            action="emit_text",
            suppression_reason=None,
            message="Rendered public read text is available for stdout.",
            evidence_ids=evidence_ids,
        )
    return PublicReadStdoutDecision(
        action="emit_json",
        suppression_reason=None,
        message="No direct text or safe binary stdout payload is available; emit JSON status.",
        evidence_ids=evidence_ids,
    )


def public_read_stdout_evidence_ids() -> tuple[str, ...]:
    return (
        "public.output.read-stdout.binary-option",
        "public.output.read-stdout.binary-docs",
        "public.output.read-stdout.binary-separators",
        "public.output.read-stdout.print-loop",
        "public.output.read-stdout.textout-routing",
        "public.output.read-stdout.w-docs",
        "public.output.read-stdout.w-per-tag-docs",
    )


def classify_public_write_output_route(
    *,
    source_paths: tuple[Path, ...],
    output_path_template: str,
    stdout: bool,
    overwrite_policy: PublicWriteOutputOverwritePolicy,
    write_policy: PublicWriteOutputPolicy,
) -> PublicWriteOutputPolicyDecision:
    evidence_ids = public_write_output_evidence_ids()
    if write_policy == "overwrite_original_in_place":
        return PublicWriteOutputPolicyDecision(
            blocker="overwrite_original_in_place_with_output_file",
            unsupported_value="overwrite_original_in_place with -o",
            message=(
                "ExifTool rejects -overwrite_original_in_place when -o output-file "
                "routing is used; public write execution must not approximate this "
                "with a rename-based transaction."
            ),
            evidence_ids=evidence_ids,
        )
    if not source_paths:
        return PublicWriteOutputPolicyDecision(
            blocker="write_output_file_type_conversion",
            unsupported_value="write-output scratch creation",
            message=(
                "Public write-output -o execution requires a source file because this "
                "route is bounded to source-backed rewrites. ExifTool can create "
                "selected metadata-only output types from scratch, but that writer "
                "seam is not implemented here."
            ),
            evidence_ids=evidence_ids,
        )
    if stdout:
        stdout_extension = public_write_output_stdout_extension(output_path_template)
        for source_path in source_paths:
            if not _write_output_extension_matches_source(source_path, stdout_extension):
                return PublicWriteOutputPolicyDecision(
                    blocker="write_output_file_type_conversion",
                    unsupported_value=(
                        f"write-output stdout type {stdout_extension or '<source>'}"
                    ),
                    message=(
                        "Public write-output stdout execution is bounded to source-backed "
                        "rewrites of the source file type. ExifTool can use '-.EXT' to "
                        "select a creatable output type, but this public route does not "
                        "create a different file type from source metadata."
                    ),
                    evidence_ids=evidence_ids,
                    source_path=source_path,
                )
        if len(source_paths) != 1:
            return PublicWriteOutputPolicyDecision(
                blocker=None,
                unsupported_value=None,
                message=(
                    "Public write-output -o stdout routing can concatenate multiple "
                    "source-backed rewritten file byte streams in source order."
                ),
                evidence_ids=evidence_ids,
            )
        source_path = source_paths[0]
        if not _write_output_extension_matches_source(source_path, stdout_extension):
            return PublicWriteOutputPolicyDecision(
                blocker="write_output_file_type_conversion",
                unsupported_value=f"write-output stdout type {stdout_extension or '<source>'}",
                message=(
                    "Public write-output stdout execution is bounded to source-backed "
                    "rewrites of the source file type. ExifTool can use '-.EXT' to "
                    "select a creatable output type, but this public route does not "
                    "create a different file type from source metadata."
                ),
                evidence_ids=evidence_ids,
            )
        return PublicWriteOutputPolicyDecision(
            blocker=None,
            unsupported_value=None,
            message=(
                "Public write-output -o stdout routing can emit one source-backed "
                "rewritten file byte stream without opening a destination path."
            ),
            evidence_ids=evidence_ids,
        )

    output_paths = public_write_output_effective_paths(
        source_paths=source_paths,
        output_path_template=output_path_template,
    )
    planned_output_keys: set[str] = set()
    for source_path, output_path in zip(source_paths, output_paths, strict=True):
        expanded_output_name = public_write_output_expanded_name(
            source_path=source_path,
            output_path_template=output_path_template,
        )
        if expanded_output_name == "":
            return PublicWriteOutputPolicyDecision(
                blocker="write_output_zero_length_path",
                unsupported_value="zero-length write-output filename",
                message=(
                    "ExifTool rejects -o format strings that expand to a zero-length "
                    "output filename; public write-output execution keeps the same guard."
                ),
                evidence_ids=evidence_ids,
                source_path=source_path,
                output_path=output_path,
            )
        if not _write_output_extension_matches_source(source_path, output_path.suffix):
            return PublicWriteOutputPolicyDecision(
                blocker="write_output_file_type_conversion",
                unsupported_value=f"write-output file type {output_path.suffix or '<none>'}",
                message=(
                    "Public write-output -o execution is bounded to source-backed rewrites "
                    "of the source file type. ExifTool can create selected output types "
                    "from metadata, but this public route does not perform file type "
                    "conversion."
                ),
                evidence_ids=evidence_ids,
                source_path=source_path,
                output_path=output_path,
            )
        if output_path.exists():
            return PublicWriteOutputPolicyDecision(
                blocker="existing_write_output_file_without_overwrite",
                unsupported_value="existing output file without overwrite policy",
                message=(
                    "ExifTool -o routing does not overwrite existing output files; "
                    "public write-output execution keeps the same existing-target guard "
                    "instead of treating -overwrite_original as target overwrite permission "
                    f"(requested output overwrite policy: {overwrite_policy})."
                ),
                evidence_ids=evidence_ids,
                source_path=source_path,
                output_path=output_path,
            )
        if source_path.resolve(strict=False) == output_path.resolve(strict=False):
            return PublicWriteOutputPolicyDecision(
                blocker="write_output_to_source_path",
                unsupported_value="write-output routing to the source path",
                message=(
                    "Public write-output -o execution will not route the output path back "
                    "to the source path; normal writes must use the explicit backup policy."
                ),
                evidence_ids=evidence_ids,
                source_path=source_path,
                output_path=output_path,
            )
        output_key = _resolved_path_key(output_path)
        if (
            output_key in planned_output_keys
            and _write_output_template_supports_multi_source_fanout(output_path_template)
        ):
            return PublicWriteOutputPolicyDecision(
                blocker="duplicate_write_output_file_route",
                unsupported_value="duplicate planned write-output path",
                message=(
                    "Public write-output -o multi-source fanout requires each source "
                    "to resolve to a distinct output path before bytes are emitted. "
                    "Add an ExifTool copy-counter token such as %c to model collision "
                    "routing without partial writes."
                ),
                evidence_ids=evidence_ids,
                source_path=source_path,
                output_path=output_path,
            )
        planned_output_keys.add(output_key)
    return PublicWriteOutputPolicyDecision(
        blocker=None,
        unsupported_value=None,
        message=(
            "Public write-output -o routing is safe for source-backed write "
            "requests after ExifTool filename and copy-counter expansion."
        ),
        evidence_ids=evidence_ids,
    )


def public_write_output_effective_paths(
    *,
    source_paths: tuple[Path, ...],
    output_path_template: str,
) -> tuple[Path, ...]:
    output_paths: list[Path] = []
    for source_path in source_paths:
        output_paths.append(
            public_write_output_effective_path(
                source_path=source_path,
                output_path_template=output_path_template,
                reserved_output_paths=tuple(output_paths),
            )
        )
    return tuple(output_paths)


def public_write_output_effective_path(
    *,
    source_path: Path,
    output_path_template: str,
    reserved_output_paths: tuple[Path, ...] = (),
) -> Path:
    expanded_name = public_write_output_expanded_name(
        source_path=source_path,
        output_path_template=output_path_template,
    )
    output_path = Path(expanded_name)
    if output_path.is_dir() or expanded_name.endswith(("/", "\\")):
        output_path = output_path / source_path.name
    return Path(
        _next_unused_filename(
            output_path.as_posix(),
            reserved_output_paths=reserved_output_paths,
        )
    )


def public_write_output_expanded_name(
    *,
    source_path: Path,
    output_path_template: str,
) -> str:
    return _filename_sprintf(output_path_template, source_path)


def public_filename_sprintf(
    *,
    format_template: str,
    source_path: Path,
    tag_context: PublicFilenameSprintfTagContext | None = None,
) -> str:
    return _filename_sprintf(format_template, source_path, tag_context)


def public_write_output_is_stdout_request(output_path_template: str) -> bool:
    return _WRITE_OUTPUT_STDOUT_RE.fullmatch(output_path_template) is not None


def public_write_output_stdout_extension(output_path_template: str) -> str | None:
    match = _WRITE_OUTPUT_STDOUT_EXTENSION_RE.fullmatch(output_path_template)
    if match is None:
        return None
    return match.group("extension")


def public_write_output_template_tokens(output_path_template: str) -> tuple[str, ...]:
    spans: list[tuple[int, int, str]] = []
    for match in _EXIFTOOL_FILENAME_SPRINTF_TOKEN_RE.finditer(output_path_template):
        spans.append((match.start(), match.end(), match.group(0)))
    for match in _EXIFTOOL_COPY_COUNTER_TOKEN_RE.finditer(output_path_template):
        spans.append((match.start(), match.end(), match.group(0)))

    tokens: list[str] = []
    last_end = -1
    for start, end, token in sorted(spans):
        if start < last_end:
            continue
        tokens.append(token)
        last_end = end
    return tuple(tokens)


def _write_output_template_supports_multi_source_fanout(output_path_template: str) -> bool:
    output_path = Path(output_path_template)
    if output_path.is_dir() or output_path_template.endswith(("/", "\\")):
        return True
    return bool(public_write_output_template_tokens(output_path_template))


def _filename_sprintf(
    format_string: str,
    source_path: Path,
    tag_context: PublicFilenameSprintfTagContext | None = None,
) -> str:
    if _EXIFTOOL_FILENAME_SPRINTF_TOKEN_RE.search(format_string) is None:
        return format_string
    parts = _filename_sprintf_parts(source_path)
    output: list[str] = []
    position = 0
    for match in _EXIFTOOL_FILENAME_SPRINTF_EXPAND_RE.finditer(format_string):
        if match.start() < position:
            continue
        output.append(format_string[position : match.start()])
        token_end = match.end()
        code = match.group(6)
        group_family = _filename_sprintf_group_family(format_string, code, token_end)
        if code == "g" and token_end < len(format_string) and format_string[token_end].isdigit():
            token_end += 1
        output.append(
            _filename_sprintf_token_value(
                parts,
                sign=match.group(1),
                width_text=match.group(2),
                dot=match.group(3),
                skip_text=match.group(4),
                modifier=match.group(5),
                code=code,
                group_family=group_family,
                tag_context=tag_context,
            )
        )
        position = token_end
    output.append(format_string[position:])
    return re.sub(r"(?!^)//+", "/", "".join(output))


def _filename_sprintf_parts(source_path: Path) -> _FilenameSprintfParts:
    source_name = source_path.as_posix()
    match = re.fullmatch(r"(.*?)([^/]*?)(\.[^./]*)?", source_name)
    if match is None:
        return _FilenameSprintfParts(
            directory="",
            directory_no_trailing_slash="",
            filename_stem="",
            extension="",
            extension_with_dot="",
            filename="",
        )
    directory = match.group(1)
    filename_stem = match.group(2)
    extension_with_dot = match.group(3) or ""
    extension = extension_with_dot[1:] if extension_with_dot else ""
    return _FilenameSprintfParts(
        directory=directory,
        directory_no_trailing_slash=directory.rstrip("/"),
        filename_stem=filename_stem,
        extension=extension,
        extension_with_dot=extension_with_dot,
        filename=f"{filename_stem}{extension_with_dot}",
    )


def _filename_sprintf_token_value(
    parts: _FilenameSprintfParts,
    *,
    sign: str,
    width_text: str,
    dot: str,
    skip_text: str,
    modifier: str,
    code: str,
    group_family: str,
    tag_context: PublicFilenameSprintfTagContext | None,
) -> str:
    if code.lower() == "d" and dot == ":":
        return _directory_level_token_value(
            _filename_part(parts, code, group_family, tag_context),
            code=code,
            sign=sign,
            width_text=width_text,
            skip_text=skip_text,
        )
    value = _filename_part(parts, code, group_family, tag_context)
    part = _substring_token_value(
        value,
        sign=sign,
        width_text=width_text,
        skip_text=skip_text,
    )
    if modifier == "u":
        return part.upper()
    if modifier == "l":
        return part.lower()
    return part


def _filename_sprintf_group_family(format_string: str, code: str, token_end: int) -> str:
    if code != "g" or token_end >= len(format_string):
        return "0"
    group_family = format_string[token_end]
    if group_family.isdigit():
        return group_family
    return "0"


def _filename_part(
    parts: _FilenameSprintfParts,
    code: str,
    group_family: str,
    tag_context: PublicFilenameSprintfTagContext | None,
) -> str:
    if code == "d":
        return parts.directory
    if code == "D":
        return parts.directory_no_trailing_slash
    if code == "f":
        return parts.filename_stem
    if code == "F":
        return parts.filename
    if code == "e":
        return parts.extension
    if code == "E":
        return parts.extension_with_dot
    if code == "t":
        return "" if tag_context is None else tag_context.tag_name
    if code == "g":
        if tag_context is None or not group_family.isdecimal():
            return ""
        group_index = int(group_family)
        if group_index >= len(tag_context.group_names):
            return ""
        return tag_context.group_names[group_index]
    if code == "s":
        return "" if tag_context is None else tag_context.suggested_extension
    if code == "o":
        return "" if tag_context is None else tag_context.original_file_name
    return ""


def _substring_token_value(
    value: str,
    *,
    sign: str,
    width_text: str,
    skip_text: str,
) -> str:
    skip = int(skip_text or "0")
    length = len(value)
    if skip >= length:
        return ""
    width = length - skip if width_text == "" else int(width_text)
    if width + skip > length:
        width = length - skip
    start = length - width - skip if sign == "-" else skip
    return value[start : start + width]


def _directory_level_token_value(
    value: str,
    *,
    code: str,
    sign: str,
    width_text: str,
    skip_text: str,
) -> str:
    path_parts = value.split("/")
    if path_parts and path_parts[-1] == "":
        path_parts = path_parts[:-1]
    skip = int(skip_text or "0")
    length = len(path_parts)
    if skip >= length:
        return ""
    width = length - skip if width_text == "" else int(width_text)
    if width + skip > length:
        width = length - skip
    start = length - width - skip if sign == "-" else skip
    part = "/".join(path_parts[start : start + width])
    if code != "D":
        part += "/"
    return part


def _next_unused_filename(
    format_string: str,
    *,
    reserved_output_paths: tuple[Path, ...] = (),
) -> str:
    if _EXIFTOOL_COPY_COUNTER_TOKEN_RE.search(format_string) is None:
        return format_string
    copy_number = 0
    alpha_number = 0
    sequence_file_directory = 1
    sequence_file_number = 1
    last_filename: str | None = None
    while True:
        filename, sequence_file_directory, sequence_file_number = _copy_counter_filename(
            format_string,
            copy_number=copy_number,
            alpha_number=alpha_number,
            sequence_file_directory=sequence_file_directory,
            sequence_file_number=sequence_file_number,
        )
        if not Path(filename).exists() and not _path_matches_reserved(
            Path(filename),
            reserved_output_paths,
        ):
            return filename
        if last_filename == filename:
            return filename
        last_filename = filename
        copy_number += 1
        alpha_number += 1


def _copy_counter_filename(
    format_string: str,
    *,
    copy_number: int,
    alpha_number: int,
    sequence_file_directory: int,
    sequence_file_number: int,
) -> tuple[str, int, int]:
    output: list[str] = []
    position = 0
    for match in _EXIFTOOL_COPY_COUNTER_EXPAND_RE.finditer(format_string):
        output.append(format_string[position : match.start()])
        value, sequence_file_directory, sequence_file_number = _copy_counter_token_value(
            copy_number=copy_number,
            alpha_number=alpha_number,
            sequence_file_directory=sequence_file_directory,
            sequence_file_number=sequence_file_number,
            sign=match.group(1),
            width_text=match.group(2),
            decimal=match.group(3),
            width_2_text=match.group(4),
            modifier=match.group(5),
            token=match.group(6),
        )
        output.append(value)
        position = match.end()
    output.append(format_string[position:])
    return "".join(output), sequence_file_directory, sequence_file_number


def _copy_counter_token_value(
    *,
    copy_number: int,
    alpha_number: int,
    sequence_file_directory: int,
    sequence_file_number: int,
    sign: str,
    width_text: str,
    decimal: str,
    width_2_text: str,
    modifier: str,
    token: str,
) -> tuple[str, int, int]:
    width = int(width_text or "0")
    width_2 = int(width_2_text or "0")
    sequence = 0
    if token == "C":
        if copy_number and decimal == ":":
            if sign == "-":
                sequence_file_directory += 1
            else:
                sequence_file_number += 1
        sequence = width + (sequence_file_directory if sign == "-" else sequence_file_number) - 1
        width = width_2
    elif not decimal and not copy_number:
        return "", sequence_file_directory, sequence_file_number
    elif width < width_2:
        width = width_2

    prefix = ""
    if token == "c" and sign:
        prefix = "-" if sign == "-" else "_"
    if modifier and modifier != "n":
        alpha = _num_to_alpha(sequence if token == "C" else alpha_number)
        padding = "a" * max(width - len(alpha), 0)
        value = f"{padding}{alpha}"
        if modifier == "u":
            value = value.upper()
        return f"{prefix}{value}", sequence_file_directory, sequence_file_number
    numeric = sequence if token == "C" else copy_number
    number = numeric + (1 if modifier else 0)
    value = f"{number:0{width}d}" if width else str(number)
    return f"{prefix}{value}", sequence_file_directory, sequence_file_number


def _num_to_alpha(number: int) -> str:
    alpha = chr(97 + (number % 26))
    while number >= 26:
        number = int(number / 26) - 1
        alpha = chr(97 + (number % 26)) + alpha
    return alpha


def _path_matches_reserved(path: Path, reserved_paths: tuple[Path, ...]) -> bool:
    path_key = _resolved_path_key(path)
    return any(path_key == _resolved_path_key(reserved_path) for reserved_path in reserved_paths)


def _resolved_path_key(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _write_output_extension_matches_source(
    source_path: Path,
    output_extension: str | None,
) -> bool:
    if output_extension is None:
        return True
    source_suffix = source_path.suffix.lower()
    output_suffix = output_extension.lower()
    if output_suffix == "":
        return True
    if source_suffix == output_suffix:
        return True
    if output_suffix in _PUBLIC_CREATABLE_WRITE_OUTPUT_SUFFIXES:
        return True
    for suffix_group in _OUTPUT_FILE_TYPE_SUFFIX_GROUPS:
        if source_suffix in suffix_group and output_suffix in suffix_group:
            return True
    return False


def public_write_output_evidence_ids() -> tuple[str, ...]:
    return (
        "public.output.write-output.o-docs",
        "public.output.write-output.stdout-routing",
        "public.output.write-output.selected-type-create",
        "public.output.write-output.creatable-type-docs",
        "public.output.write-output.can-create-types",
        "public.output.write-output.exif-route",
        "public.output.write-output.exv-route",
        "public.output.write-output.filename-tokens",
        "public.output.write-output.overwrite-move",
        "public.output.write-output.incompatible-side-effects",
        "public.output.write-output.writeinfo-side-effects",
    )


def public_write_output_exv_materializer_contract() -> PublicSelectedOutputMaterializerContract:
    return PublicSelectedOutputMaterializerContract(
        selected_output_type="exv",
        decision="terminal_blocked",
        reason="requires_exiftool_writejpeg_directory_materializer",
        message=(
            "Selected-output EXV cannot be implemented as a source-byte or JPEG APP-segment "
            "copy. ExifTool converts source metadata through tagsFromFile/new values, then "
            "creates or rewrites an EXV stream through the JPEG writer, emitting the 0xff01 "
            "Exiv2 signature, writable JPEG-family directories, and an EXV EOI marker. "
            "ExifModern now owns package-local EXV wrapper primitives for the signature, "
            "JPEG-style segment framing, WriteMultiSegment-style splitting, and trailer "
            "drop behavior. It also owns a bounded EXV materializer for already-owned "
            "EXIF TIFF payload bytes. Public selected-output execution now routes only "
            "that owned EXIF TIFF payload slice: direct bounded EXIF scalar assignment "
            "materialization, source EXIF TIFF scalar mutation through the owned TIFF "
            "IFD rewriter, source-backed EXIF TIFF payload wrapping, and exact "
            "source-backed Photoshop APP13/XMP/ICC/COM payload fanout. It also routes "
            "bounded IPTC ApplicationRecord assignments through the owned JPEG APP13 "
            "Photoshop/IPTC materializer. Broader WriteDirectory/WriteTIFF coverage "
            "for generic Photoshop APP13 resources and generated extended XMP remains "
            "deferred."
        ),
        evidence_ids=(
            "public.output.exv.stdout-selected-type",
            "public.output.exv.creatable-conversion",
            "public.output.exv.create-docs",
            "public.output.exv.writejpeg-route",
            "public.output.exv.signature",
            "public.output.exv.synthetic-eoi",
            "public.output.exv.segment-materialization",
            "public.output.exv.final-eoi",
        ),
        owned_primitives_checked=(
            "src/exifmodern/formats/jpeg/container.py scan_jpeg_segments reads JPEG streams "
            "beginning with SOI.",
            "src/exifmodern/formats/jpeg/segment_writer.py encode_jpeg_segment writes one "
            "bounded JPEG segment.",
            "src/exifmodern/formats/jpeg/segment_writer.py replace_jpeg_segment replaces one "
            "existing segment.",
            "src/exifmodern/formats/jpeg/app_segment_delete.py delete_jpeg_app_segments deletes "
            "owned APP6 segments and repairs AFCP trailer offsets.",
            "src/exifmodern/formats/exv/writer.py EXV wrapper primitive validates 0xff01 "
            "Exiv2 streams, emits JPEG-style metadata segments, splits multi-segment "
            "EXIF/ICC payloads, and drops trailers after EXV EOI.",
        ),
        insufficient_primitives=(
            "No owned primitive performs ExifTool's selected-output tagsFromFile/new-value "
            "fanout into all writable directory data.",
            "No owned primitive ports Photoshop/IPTC APP13 WriteDirectory materialization "
            "for EXV selected output.",
            "No owned primitive ports WriteMultiXMP ordering and splitting for generated "
            "EXV XMP APP segments.",
            "No owned primitive has oracle-proven readback parity for every JPEG-family "
            "writable directory projected into a 0xff01 Exiv2 selected-output stream.",
        ),
        required_dependencies=(
            "Package-local EXV stream parser/writer that accepts 0xff01 Exiv2 and emits "
            "0xffd9 EOI according to the source writer contract.",
            "Shared writable-directory materializer equivalent to ExifTool WriteDirectory "
            "and WriteTIFF for EXIF selected output.",
            "JPEG-family generated segment ordering and multi-segment emission for EXIF, "
            "Photoshop/IPTC, XMP, ICC, Ducky, Adobe, and COM directories.",
            "Source-backed tagsFromFile/new-value projection that feeds the EXV materializer "
            "instead of copying existing source bytes.",
        ),
        terminal_contract_artifact=(
            "artifacts/parity-suite/batch237-lane-b/exv-selected-output-contract.json"
        ),
    )


def public_output_visible_graph(
    graph: ReadGraph,
    *,
    include_unknown_tags: bool = False,
) -> ReadGraph:
    tags = public_output_visible_tags(graph.tags, include_unknown_tags=include_unknown_tags)
    if len(tags) == len(graph.tags):
        return graph
    return replace(graph, tags=tags)


def public_output_visible_tags(
    tags: list[ReadTag],
    *,
    include_unknown_tags: bool = False,
) -> list[ReadTag]:
    if include_unknown_tags:
        return tags
    return [tag for tag in tags if public_output_suppression_for_tag(tag) is None]


def public_output_suppression_for_tag(tag: ReadTag) -> PublicOutputSuppression | None:
    if _is_internal_exe_planner_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_internal_exe_planner",
            evidence_ids=("public.output.suppression.internal-exe-planner",),
        )
    if _is_macos_sidecar_container_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_macos_sidecar_container",
            evidence_ids=("public.output.suppression.macos-sidecar-container",),
        )
    if _is_tiff_dynamic_unknown_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_dynamic_unknown_tag",
            evidence_ids=(
                "public.output.suppression.dynamic-unknown-docs",
                "public.output.suppression.unknown-default-suppression",
                "public.output.suppression.dynamic-unknown-synthesis",
            ),
        )
    if _is_unknown_pm_maker_note_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_unknown_makernote",
            evidence_ids=(
                "public.output.suppression.unknown-gettaginfo",
                "public.output.suppression.unknown-maker-note",
            ),
        )
    if _is_apple_unknown_makernote_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_unknown_makernote",
            evidence_ids=(
                "public.output.suppression.unknown-gettaginfo",
                "public.output.suppression.apple-maker-note-unknown",
            ),
        )
    if _is_matroska_unknown_tag(tag):
        return PublicOutputSuppression(
            reason="exiftool_unknown_matroska",
            evidence_ids=(
                "public.output.suppression.unknown-gettaginfo",
                "public.output.suppression.matroska-structural-unknown",
                "public.output.suppression.matroska-test-unknown",
            ),
        )
    return None


def _is_internal_exe_planner_tag(tag: ReadTag) -> bool:
    if not tag.provenance.table_name.startswith("Image::ExifTool::EXE::"):
        return False
    return tag.provenance.family_1_group == "EXE" and tag.name in {"ExeSubformat", "ExeRoute"}


def _is_macos_sidecar_container_tag(tag: ReadTag) -> bool:
    if tag.provenance.table_name != "Image::ExifTool::MacOS::Main":
        return False
    return tag.name in {"ATTR", "RSRC"} and tag.provenance.family_1_group == "MacOS"


def _is_apple_unknown_makernote_tag(tag: ReadTag) -> bool:
    provenance = tag.provenance
    if provenance.table_name != "Image::ExifTool::Apple::Main":
        return False
    if provenance.family_0_group != "MakerNotes" or provenance.family_1_group != "Apple":
        return False
    return tag.name in _APPLE_DECLARED_UNKNOWN_TAGS or _is_dynamic_apple_unknown_tag(tag.name)


def _is_tiff_dynamic_unknown_tag(tag: ReadTag) -> bool:
    if tag.provenance.source != "jpeg-app1-tiff-dynamic-unknown":
        return False
    if tag.provenance.table_name not in {
        "Image::ExifTool::Exif::Main",
        "Image::ExifTool::GPS::Main",
    }:
        return False
    return _TIFF_DYNAMIC_UNKNOWN_TAG_RE.fullmatch(tag.name) is not None


def _is_unknown_pm_maker_note_tag(tag: ReadTag) -> bool:
    provenance = tag.provenance
    if provenance.table_name != "Image::ExifTool::Unknown::Main":
        return False
    return provenance.family_0_group == "MakerNotes" and provenance.family_1_group == "MakerUnknown"


def _is_dynamic_apple_unknown_tag(tag_name: str) -> bool:
    return _APPLE_DYNAMIC_UNKNOWN_TAG_RE.fullmatch(tag_name) is not None


def _is_matroska_unknown_tag(tag: ReadTag) -> bool:
    provenance = tag.provenance
    if provenance.table_name != "Image::ExifTool::Matroska::Main":
        return False
    if provenance.family_0_group != "Matroska":
        return False
    return tag.name in _MATROSKA_DECLARED_UNKNOWN_TAGS
