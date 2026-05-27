"""Source-backed public boundary for ExifTool config/plugin execution."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.json_types import JsonObject
from exifmodern.provenance.public_interface import public_evidence_values

if TYPE_CHECKING:
    from exifmodern.public_interface.list_catalog import PublicListCatalog
    from exifmodern.services.tag_lookup_runtime import TagLookupRuntimeOverlay


class _PublicEvidenceIdsMixin:
    evidence_ids: tuple[str, ...]


PUBLIC_CONFIG_EARLY_LOAD_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.early-config-collection",
    "public.config.config-file-load",
    "public.config.config-docs",
)

PUBLIC_CONFIG_FRAME_LIFECYCLE_EVIDENCE_IDS: tuple[str, ...] = (
    "public.batch.common-args-loop",
    "public.config.exiftool-object-frame",
    "public.config.execute-frame-replay",
    "public.config.default-arguments-docs",
)

PUBLIC_CONFIG_MATERIALIZATION_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.user-tags-docs",
    "public.config.user-file-types-docs",
    "public.config.config-file-load-merge",
    "public.config.taglookup-runtime-resolution",
)

PUBLIC_CONFIG_FULL_FRAME_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.early-config-collection",
    "public.batch.common-args-loop",
    "public.config.exiftool-object-frame",
    "public.config.execute-frame-replay",
    "public.batch.stay-open-parse-shutdown",
    "public.batch.argfile-docs",
    "public.config.config-docs",
    "public.config.execute-config-use-docs",
    "public.config.default-api-arguments-docs",
    "public.config.user-options-instance-copy",
)

PUBLIC_CONFIG_EXTENSION_CLUSTER_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.shortcuts-docs",
    "public.config.user-tags-docs",
    "public.config.user-file-types-docs",
    "public.config.default-api-arguments-docs",
    "public.config.magic-regex-test",
    "public.config.supported-filetype-query",
    "public.config.config-file-load-merge",
    "public.config.use-module-load",
    "public.config.writer-route",
)

PUBLIC_CONFIG_API_BOUNDARY_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.default-api-arguments-docs",
    "public.config.user-options-instance-copy",
    "public.config.api-option-docs",
    "public.config.list-separator-docs",
)

PUBLIC_CONFIG_RELEASE_DECISION_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.early-config-collection",
    "public.config.exiftool-object-frame",
    "public.config.execute-frame-replay",
    "public.config.api-charset-parse",
    "public.config.language-parse",
    "public.config.use-module-load",
    "public.config.config-html-surface",
    "public.config.config-file-load-merge-wide",
)

PUBLIC_CONFIG_VM_BOUNDARY_EVIDENCE_IDS: tuple[str, ...] = (
    "public.config.early-config-collection",
    "public.config.config-file-load",
    "public.config.use-module-load",
    "public.config.mwg-load",
    "public.config.use-docs",
    "public.config.config-docs",
    "public.config.config-html-runtime-effects",
)


@dataclass(frozen=True)
class PublicSafeConfigUseOptions:
    """Typed config/use subset that never loads external Perl code."""

    disable_default_config: bool = False
    use_mwg: bool = False
    suppressed_config_files_after_disable: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicSafeConfigOptionEffect:
    """Effect of a reviewed public -config token."""

    disable_default_config: bool = False
    suppressed_config_file: str | None = None


@dataclass(frozen=True)
class PublicConfigPluginVmBoundaryContract(_PublicEvidenceIdsMixin):
    """Reviewed boundary between safe markers and host Perl config/plugin effects."""

    safe_config_forms: tuple[str, ...]
    safe_use_modules: tuple[str, ...]
    safe_source_backed_expansions: tuple[str, ...]
    trusted_vm_execution: Literal["not_safe_expression_vm_backed"]
    trusted_host_contract: tuple[str, ...]
    arbitrary_config_blocker: str
    arbitrary_plugin_blocker: str
    evidence_ids: tuple[str, ...]
    remaining_blockers: tuple[str, ...]


@dataclass(frozen=True)
class PublicTrustedConfigShortcut:
    """Shortcut effect returned by a future trusted config host."""

    name: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class PublicTrustedConfigDefaultArguments:
    """Command-line arguments returned by a future trusted config host."""

    source_config: str
    arguments: tuple[str, ...]


type PublicTrustedConfigApiOptionValue = str | int | float | bool
type PublicTrustedConfigMagicSniffOutcome = Literal[
    "matched_recognized_magic_only",
    "blocked_perl_regex_magic",
    "blocked_base_type_magic_conflict",
    "not_matched",
]


@dataclass(frozen=True)
class PublicTrustedConfigUserDefinedTag:
    """User-defined tag effect returned by a trusted config host."""

    source_config: str
    table_name: str
    tag_id: str
    name: str
    writable: str | bool
    write_group: str | None = None


@dataclass(frozen=True)
class PublicTrustedConfigUserDefinedFileType:
    """User-defined file type effect returned by a trusted config host."""

    source_config: str
    extension: str
    base_type: str | None = None
    mime_type: str | None = None
    description: str | None = None
    magic_pattern: str | None = None
    writable: bool | None = None


@dataclass(frozen=True)
class PublicTrustedConfigMagicSniffResult:
    """Bounded file-type sniff result for a trusted user-defined file type."""

    source_config: str
    extension: str
    outcome: PublicTrustedConfigMagicSniffOutcome
    supported_reader_route: bool
    blocker_code: str | None
    detail: str


@dataclass(frozen=True)
class PublicTrustedConfigDefaultApiOption:
    """Default API option effect returned by a trusted config host."""

    source_config: str
    name: str
    value: PublicTrustedConfigApiOptionValue

    @property
    def api_argument(self) -> str:
        return f"{self.name}={_trusted_config_api_option_value_text(self.value)}"


@dataclass(frozen=True)
class PublicTrustedConfigEffects:
    """Typed effects returned by a trusted config host after Perl isolation."""

    shortcuts: tuple[PublicTrustedConfigShortcut, ...] = ()
    default_arguments: PublicTrustedConfigDefaultArguments | None = None
    user_defined_tags: tuple[PublicTrustedConfigUserDefinedTag, ...] = ()
    user_defined_file_types: tuple[PublicTrustedConfigUserDefinedFileType, ...] = ()
    default_api_options: tuple[PublicTrustedConfigDefaultApiOption, ...] = ()


@dataclass(frozen=True)
class PublicTrustedConfigFrame:
    """One execute/stay-open frame with trusted config effects scoped to the request."""

    index: int
    args: tuple[str, ...]
    effective_args: tuple[str, ...]
    execute_id: str | None
    trusted_effects: PublicTrustedConfigEffects
    default_config_disabled: bool


@dataclass(frozen=True)
class PublicTrustedConfigFrameLifecycle(_PublicEvidenceIdsMixin):
    """Trusted config effects materialized across a bounded multi-command request."""

    frames: tuple[PublicTrustedConfigFrame, ...]
    default_config_disabled: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicTrustedConfigFrameLifecycleContract(_PublicEvidenceIdsMixin):
    """Source-backed lifecycle contract for trusted config effects across frames."""

    arbitrary_perl_config_execution: Literal["blocked"]
    frame_scope: Literal["execute_and_stay_open_command_frame"]
    default_config_disable: Literal["suppresses_default_config_host_effects_before_frames"]
    default_arguments_lifecycle: Literal["prepended_to_each_frame_after_config_handling"]
    default_api_options_lifecycle: Literal["applied_to_each_frame_before_command_line_api_options"]
    request_scoped_overlay_lifecycle: Literal["materialized_per_frame_without_global_mutation"]
    config_in_argfile_policy: Literal["blocked_by_argfile_parser"]
    evidence_ids: tuple[str, ...]
    trust_boundary: tuple[str, ...]
    remaining_blockers: tuple[str, ...]


@dataclass(frozen=True)
class PublicTrustedConfigMaterializationContract(_PublicEvidenceIdsMixin):
    """Request-scoped materialization contract for trusted config host effects."""

    arbitrary_perl_config_execution: Literal["blocked"]
    runtime_scope: Literal["request_scoped_overlay"]
    public_global_table_mutation: Literal["blocked"]
    trusted_tag_lookup_materialization: tuple[str, ...]
    trusted_file_type_materialization: tuple[str, ...]
    write_execution_policy: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    remaining_blockers: tuple[str, ...]


@dataclass(frozen=True)
class PublicTrustedExtensionClusterContract(_PublicEvidenceIdsMixin):
    """Release boundary for trusted config/plugin extension seams."""

    magic_pattern_file_sniffing: tuple[str, ...]
    user_defined_tag_write_routes: tuple[str, ...]
    shortcut_and_default_argument_breadth: tuple[str, ...]
    arbitrary_config_and_use_boundary: tuple[str, ...]
    trust_boundary: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    remaining_blockers: tuple[str, ...]


type PublicConfigPluginReleaseDecisionStatus = Literal[
    "external_trusted_host_required",
    "not_public_runtime_feature",
    "blocked_until_native_writer_contract",
    "blocked_until_base_type_capability_model",
]


@dataclass(frozen=True)
class PublicConfigPluginReleaseDecisionBlocker(_PublicEvidenceIdsMixin):
    """Terminal release decision for one unsafe config/plugin compatibility seam."""

    code: str
    surface: str
    status: PublicConfigPluginReleaseDecisionStatus
    exiftool_behavior: str
    public_runtime_decision: str
    external_test_contract: str
    evidence_ids: tuple[str, ...]

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "surface": self.surface,
            "status": self.status,
            "exiftool_behavior": self.exiftool_behavior,
            "public_runtime_decision": self.public_runtime_decision,
            "external_test_contract": self.external_test_contract,
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicConfigPluginReleaseDecisionContract(_PublicEvidenceIdsMixin):
    """Batch 234 release decision for arbitrary config/plugin execution."""

    family_id: str
    status: Literal["bounded_effects_closed_with_terminal_release_blockers"]
    public_runtime_import_policy: str
    bounded_effects_closed: tuple[str, ...]
    release_decision_blockers: tuple[PublicConfigPluginReleaseDecisionBlocker, ...]
    evidence_ids: tuple[str, ...]
    focused_tests: tuple[str, ...]

    def to_json_value(self, *, include_evidence_ids: bool = False) -> JsonObject:
        payload: JsonObject = {
            "family_id": self.family_id,
            "status": self.status,
            "public_runtime_import_policy": self.public_runtime_import_policy,
            "bounded_effects_closed": list(self.bounded_effects_closed),
            "release_decision_blockers": [
                blocker.to_json_value(include_evidence_ids=include_evidence_ids)
                for blocker in self.release_decision_blockers
            ],
            "focused_tests": list(self.focused_tests),
        }
        if include_evidence_ids:
            payload["evidence_ids"] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicTrustedConfigApiBoundaryContract(_PublicEvidenceIdsMixin):
    """Source-backed trusted config API effects admitted by public read parsing."""

    trusted_effect_lifecycle: Literal["typed_trusted_host_payload_to_api_arguments"]
    source_backed_read_api_options: tuple[str, ...]
    arbitrary_config_execution: Literal["blocked"]
    evidence_ids: tuple[str, ...]
    remaining_blockers: tuple[str, ...]


@dataclass(frozen=True)
class PublicConfigDefinedEffectBoundary(_PublicEvidenceIdsMixin):
    """A config-defined effect and its public-runtime trust boundary."""

    surface: Literal[
        "user_defined_tags",
        "user_defined_shortcuts",
        "user_defined_file_types",
        "default_api_options",
        "user_defined_command_line_arguments",
    ]
    exiftool_storage: str
    exiftool_effect: str
    public_runtime_contract: Literal[
        "blocked_until_trusted_host_effects",
        "trusted_host_return_only",
    ]
    trusted_host_payload: str
    blocker_code: str
    blocker_message: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicConfigDefinedEffectsContract:
    """Source-backed config effect contract for trusted-host integration."""

    arbitrary_config_execution: Literal["blocked"]
    default_arguments_insertion: Literal["before_all_non_config_arguments"]
    shortcuts_without_host_execution: Literal["not_representable"]
    default_arguments_without_host_execution: Literal["not_representable"]
    effect_boundaries: tuple[PublicConfigDefinedEffectBoundary, ...]


def parse_public_safe_config_use_options(args: Sequence[str]) -> PublicSafeConfigUseOptions:
    """Parse reviewed -config/-use forms without executing config or plug-in code."""

    disable_default_config = False
    use_mwg = False
    suppressed_config_files_after_disable: list[str] = []
    index = 0
    while index < len(args):
        lower_arg = args[index].lower()
        if lower_arg == "-config":
            effect = parse_safe_public_config_option(
                args[index],
                args,
                index,
                default_config_already_disabled=disable_default_config,
            )
            disable_default_config = effect.disable_default_config or disable_default_config
            if effect.suppressed_config_file is not None:
                suppressed_config_files_after_disable.append(effect.suppressed_config_file)
            index += 2
            continue
        if lower_arg == "-use":
            use_mwg = parse_safe_public_use_option(args[index], args, index) or use_mwg
            index += 2
            continue
        index += 1
    return PublicSafeConfigUseOptions(
        disable_default_config=disable_default_config,
        use_mwg=use_mwg,
        suppressed_config_files_after_disable=tuple(suppressed_config_files_after_disable),
    )


def trusted_public_config_shortcut(
    name: str,
    targets: Sequence[str],
) -> PublicTrustedConfigShortcut:
    """Validate a shortcut map entry returned by a trusted host.

    This helper does not read or execute config files. It only admits a typed
    string-to-string-list effect after an external trusted host has already
    isolated ExifTool's Perl config execution.
    """

    shortcut_name = name.strip()
    if not shortcut_name:
        raise argparse.ArgumentTypeError("trusted config shortcut name must not be empty")
    target_tuple = tuple(targets)
    if not target_tuple:
        raise argparse.ArgumentTypeError(
            f"trusted config shortcut {shortcut_name!r} must contain at least one target"
        )
    for target in target_tuple:
        if not target:
            raise argparse.ArgumentTypeError(
                f"trusted config shortcut {shortcut_name!r} contains an empty target"
            )
    return PublicTrustedConfigShortcut(name=shortcut_name, targets=target_tuple)


def trusted_public_config_default_arguments(
    source_config: str,
    arguments: Sequence[str],
) -> PublicTrustedConfigDefaultArguments:
    """Validate command-line defaults returned by a trusted config host."""

    if not source_config:
        raise argparse.ArgumentTypeError("trusted config default arguments require source_config")
    argument_tuple = tuple(arguments)
    for argument in argument_tuple:
        if argument == "-config":
            raise argparse.ArgumentTypeError(
                "trusted config default arguments must not contain -config; "
                "ExifTool inserts UserDefined::Arguments after early -config handling"
            )
    return PublicTrustedConfigDefaultArguments(
        source_config=source_config,
        arguments=argument_tuple,
    )


def trusted_public_config_user_defined_tag(
    *,
    source_config: str,
    table_name: str,
    tag_id: str,
    name: str,
    writable: str | bool,
    write_group: str | None = None,
) -> PublicTrustedConfigUserDefinedTag:
    """Validate a user-defined tag effect returned by a trusted host."""

    if not source_config:
        raise argparse.ArgumentTypeError("trusted config user-defined tags require source_config")
    if not table_name.startswith("Image::ExifTool::"):
        raise argparse.ArgumentTypeError(
            "trusted config user-defined tag table must be an Image::ExifTool table"
        )
    if not tag_id:
        raise argparse.ArgumentTypeError("trusted config user-defined tag requires tag_id")
    tag_name = name.strip()
    if not tag_name:
        raise argparse.ArgumentTypeError("trusted config user-defined tag name must not be empty")
    if isinstance(writable, str) and not writable:
        raise argparse.ArgumentTypeError(
            "trusted config user-defined tag writable must not be empty"
        )
    if write_group is not None and not write_group:
        raise argparse.ArgumentTypeError(
            "trusted config user-defined tag write_group must not be empty"
        )
    return PublicTrustedConfigUserDefinedTag(
        source_config=source_config,
        table_name=table_name,
        tag_id=tag_id,
        name=tag_name,
        writable=writable,
        write_group=write_group,
    )


def trusted_public_config_user_defined_file_type(
    *,
    source_config: str,
    extension: str,
    base_type: str | None = None,
    mime_type: str | None = None,
    description: str | None = None,
    magic_pattern: str | None = None,
    writable: bool | None = None,
) -> PublicTrustedConfigUserDefinedFileType:
    """Validate a user-defined file type effect returned by a trusted host."""

    if not source_config:
        raise argparse.ArgumentTypeError("trusted config file types require source_config")
    normalized_extension = extension.strip().upper()
    if not normalized_extension or not normalized_extension.isalnum():
        raise argparse.ArgumentTypeError("trusted config file type extension must be alphanumeric")
    if base_type is not None and magic_pattern is not None:
        raise argparse.ArgumentTypeError(
            "trusted config file type must not define Magic with BaseType; "
            "ExifTool config.html says Magic should not be defined when BaseType is present"
        )
    if base_type is None and magic_pattern is None and description is None:
        raise argparse.ArgumentTypeError(
            "trusted config file type requires BaseType, Magic, or Description"
        )
    return PublicTrustedConfigUserDefinedFileType(
        source_config=source_config,
        extension=normalized_extension,
        base_type=base_type,
        mime_type=mime_type,
        description=description,
        magic_pattern=magic_pattern,
        writable=writable,
    )


def trusted_public_config_default_api_option(
    *,
    source_config: str,
    name: str,
    value: PublicTrustedConfigApiOptionValue,
) -> PublicTrustedConfigDefaultApiOption:
    """Validate a default API option effect returned by a trusted host."""

    if not source_config:
        raise argparse.ArgumentTypeError("trusted config default API options require source_config")
    option_name = name.strip()
    if not option_name:
        raise argparse.ArgumentTypeError("trusted config default API option name must not be empty")
    if re.search(r"[^\w]", option_name):
        raise argparse.ArgumentTypeError(
            f"trusted config default API option name is not plain: {option_name}"
        )
    return PublicTrustedConfigDefaultApiOption(
        source_config=source_config,
        name=option_name,
        value=value,
    )


def trusted_public_config_effects(
    *,
    shortcuts: Sequence[PublicTrustedConfigShortcut] = (),
    default_arguments: PublicTrustedConfigDefaultArguments | None = None,
    user_defined_tags: Sequence[PublicTrustedConfigUserDefinedTag] = (),
    user_defined_file_types: Sequence[PublicTrustedConfigUserDefinedFileType] = (),
    default_api_options: Sequence[PublicTrustedConfigDefaultApiOption] = (),
) -> PublicTrustedConfigEffects:
    """Collect typed trusted-host config effects without executing config Perl."""

    return PublicTrustedConfigEffects(
        shortcuts=tuple(shortcuts),
        default_arguments=default_arguments,
        user_defined_tags=tuple(user_defined_tags),
        user_defined_file_types=tuple(user_defined_file_types),
        default_api_options=tuple(default_api_options),
    )


def empty_trusted_public_config_effects() -> PublicTrustedConfigEffects:
    """Return an immutable empty trusted-effect set for disabled config frames."""

    return PublicTrustedConfigEffects()


def apply_trusted_public_config_default_arguments(
    args: Sequence[str],
    trusted_defaults: PublicTrustedConfigDefaultArguments,
) -> tuple[str, ...]:
    """Apply already-trusted config arguments at ExifTool's insertion point."""

    return trusted_defaults.arguments + tuple(args)


def trusted_public_config_default_api_arguments(
    trusted_effects: PublicTrustedConfigEffects,
) -> tuple[str, ...]:
    """Return default API options as ExifTool-style -api arguments."""

    api_args: list[str] = []
    for option in trusted_effects.default_api_options:
        api_args.extend(("-api", option.api_argument))
    return tuple(api_args)


def trusted_public_config_effective_args(
    args: Sequence[str],
    trusted_effects: PublicTrustedConfigEffects,
    *,
    default_config_disabled: bool = False,
) -> tuple[str, ...]:
    """Apply trusted defaults at ExifTool's per-command frame insertion points."""

    if default_config_disabled:
        return tuple(args)
    effective_args = tuple(args)
    if trusted_effects.default_arguments is not None:
        effective_args = apply_trusted_public_config_default_arguments(
            effective_args,
            trusted_effects.default_arguments,
        )
    return trusted_public_config_default_api_arguments(trusted_effects) + effective_args


def trusted_public_config_active_effects(
    trusted_effects: PublicTrustedConfigEffects,
    *,
    default_config_disabled: bool,
) -> PublicTrustedConfigEffects:
    """Return frame-local trusted effects after early -config disable handling."""

    if default_config_disabled:
        return empty_trusted_public_config_effects()
    return trusted_effects


def trusted_public_config_execute_frame_lifecycle(
    args: Sequence[str],
    trusted_effects: PublicTrustedConfigEffects,
    *,
    default_config_disabled: bool = False,
) -> PublicTrustedConfigFrameLifecycle:
    """Build ExifTool-style execute frames with trusted effects applied per frame."""

    from exifmodern.public_interface.batch_protocol import build_batch_execution_requests

    active_effects = trusted_public_config_active_effects(
        trusted_effects,
        default_config_disabled=default_config_disabled,
    )
    frames = tuple(
        PublicTrustedConfigFrame(
            index=request.index,
            args=request.args,
            effective_args=trusted_public_config_effective_args(
                request.args,
                active_effects,
                default_config_disabled=default_config_disabled,
            ),
            execute_id=request.execute_id,
            trusted_effects=active_effects,
            default_config_disabled=default_config_disabled,
        )
        for request in build_batch_execution_requests(args)
    )
    return PublicTrustedConfigFrameLifecycle(
        frames=frames,
        default_config_disabled=default_config_disabled,
        evidence_ids=PUBLIC_CONFIG_FRAME_LIFECYCLE_EVIDENCE_IDS,
    )


def trusted_public_config_supported_read_extensions(
    trusted_effects: PublicTrustedConfigEffects,
) -> frozenset[str]:
    """Return request-scoped directory-read extensions for supported trusted file types."""

    return frozenset(
        f".{file_type.extension.lower()}"
        for file_type in trusted_effects.user_defined_file_types
        if file_type.base_type is not None
    )


def trusted_public_config_magic_sniff_file(
    path: Path,
    trusted_effects: PublicTrustedConfigEffects,
) -> tuple[PublicTrustedConfigMagicSniffResult, ...]:
    """Sniff safe literal Magic prefixes without promoting unsupported reader routes.

    ExifTool evaluates user-defined Magic as a Perl regex anchored at the start
    of the binary buffer.  Public runtime only handles plain literal prefixes;
    arbitrary regex syntax remains a blocker because Python regex semantics are
    not ExifTool's Perl regex contract.
    """

    sniffable_types = tuple(
        file_type
        for file_type in trusted_effects.user_defined_file_types
        if file_type.magic_pattern is not None
    )
    if not sniffable_types:
        return ()
    max_prefix_length = max(len(file_type.magic_pattern or "") for file_type in sniffable_types)
    with path.open("rb") as file:
        prefix = file.read(max_prefix_length)
    return tuple(
        trusted_public_config_magic_sniff_prefix(prefix, file_type) for file_type in sniffable_types
    )


def trusted_public_config_magic_sniff_prefix(
    prefix: bytes,
    file_type: PublicTrustedConfigUserDefinedFileType,
) -> PublicTrustedConfigMagicSniffResult:
    """Sniff one trusted file type against a caller-supplied file prefix."""

    if file_type.magic_pattern is None:
        return PublicTrustedConfigMagicSniffResult(
            source_config=file_type.source_config,
            extension=file_type.extension,
            outcome="not_matched",
            supported_reader_route=file_type.base_type is not None,
            blocker_code=None,
            detail="Trusted file type has no Magic pattern to sniff.",
        )
    if file_type.base_type is not None:
        return PublicTrustedConfigMagicSniffResult(
            source_config=file_type.source_config,
            extension=file_type.extension,
            outcome="blocked_base_type_magic_conflict",
            supported_reader_route=False,
            blocker_code="magic_with_base_type_not_supported",
            detail=(
                "ExifTool config.html says Magic should not be defined when BaseType "
                "is present; public runtime rejects this typed effect instead of "
                "guessing precedence."
            ),
        )
    literal = _trusted_magic_literal_bytes(file_type.magic_pattern)
    if literal is None:
        return PublicTrustedConfigMagicSniffResult(
            source_config=file_type.source_config,
            extension=file_type.extension,
            outcome="blocked_perl_regex_magic",
            supported_reader_route=False,
            blocker_code="perl_regex_magic_pattern_not_supported",
            detail=(
                "User-defined Magic is a Perl regular expression matched at the start "
                "of the file buffer; public runtime only sniffs plain Latin-1 literal "
                "prefixes and does not emulate arbitrary Perl regex syntax."
            ),
        )
    if prefix.startswith(literal):
        return PublicTrustedConfigMagicSniffResult(
            source_config=file_type.source_config,
            extension=file_type.extension,
            outcome="matched_recognized_magic_only",
            supported_reader_route=False,
            blocker_code="magic_only_file_type_recognized_not_supported",
            detail=(
                "Magic-only trusted file type matched, but ExifTool config.html defines "
                "types without BaseType as recognized but not supported, so no native "
                "reader route is promoted."
            ),
        )
    return PublicTrustedConfigMagicSniffResult(
        source_config=file_type.source_config,
        extension=file_type.extension,
        outcome="not_matched",
        supported_reader_route=False,
        blocker_code=None,
        detail="Trusted literal Magic prefix did not match the supplied file prefix.",
    )


def trusted_public_config_expand_shortcut_tokens(
    raw_tokens: Sequence[str],
    trusted_effects: PublicTrustedConfigEffects,
    *,
    remove_value_suffix: bool = False,
    skip_excluded_targets: bool = False,
) -> tuple[str, ...]:
    """Expand typed trusted-host shortcut effects after built-in shortcut parsing."""

    expanded: list[str] = []
    shortcuts = {shortcut.name.casefold(): shortcut for shortcut in trusted_effects.shortcuts}
    for raw_token in raw_tokens:
        prefix, tag = _split_trusted_shortcut_group_prefix(raw_token)
        tag_name, value_suffix = _split_trusted_shortcut_value_suffix(
            tag,
            remove_value_suffix=remove_value_suffix,
        )
        shortcut = shortcuts.get(tag_name.casefold())
        if shortcut is None:
            expanded.append(raw_token)
            continue
        for target in shortcut.targets:
            if skip_excluded_targets and target.startswith("-"):
                continue
            target_prefix, target_name = _split_trusted_shortcut_group_prefix(target)
            if target_prefix:
                expanded.append(f"{target_prefix}{target_name}{value_suffix}")
            else:
                expanded.append(f"{prefix}{target_name}{value_suffix}")
    return tuple(expanded)


def public_list_catalog_with_trusted_config_effects(
    catalog: PublicListCatalog,
    trusted_effects: PublicTrustedConfigEffects,
) -> PublicListCatalog:
    """Return a non-global public list catalog overlay for trusted config effects."""

    from exifmodern.public_interface.list_catalog import PublicListCatalog

    available_tags = _casefold_sorted_unique(
        (*catalog.available_tags, *(tag.name for tag in trusted_effects.user_defined_tags))
    )
    writable_tags = _casefold_sorted_unique(
        (
            *catalog.writable_tags,
            *(
                tag.name
                for tag in trusted_effects.user_defined_tags
                if _trusted_config_tag_is_writable(tag)
            ),
        )
    )
    recognized_extensions = set(catalog.recognized_extensions)
    supported_extensions = set(catalog.supported_extensions)
    writable_extensions = set(catalog.writable_extensions)
    extension_descriptions = dict(catalog.extension_descriptions)
    for file_type in trusted_effects.user_defined_file_types:
        dotted_extension = f".{file_type.extension.lower()}"
        recognized_extensions.add(dotted_extension)
        if file_type.base_type is not None:
            supported_extensions.add(dotted_extension)
        if file_type.writable is True:
            writable_extensions.add(dotted_extension)
        if file_type.description is not None:
            extension_descriptions[file_type.extension] = file_type.description

    groups_by_family = {
        family: tuple(groups) for family, groups in catalog.groups_by_family.items()
    }
    command_line_shortcuts = _casefold_sorted_unique(
        (
            *catalog.command_line_shortcuts,
            *(shortcut.name for shortcut in trusted_effects.shortcuts),
        )
    )
    shortcut_targets = {
        shortcut: tuple(targets) for shortcut, targets in catalog.shortcut_targets.items()
    }
    for shortcut in trusted_effects.shortcuts:
        shortcut_targets[shortcut.name] = shortcut.targets

    return PublicListCatalog(
        available_tags=available_tags,
        command_line_shortcuts=command_line_shortcuts,
        writable_tags=writable_tags,
        supported_extensions=frozenset(supported_extensions),
        recognized_extensions=frozenset(recognized_extensions),
        writable_extensions=frozenset(writable_extensions),
        extension_descriptions=extension_descriptions,
        deletable_groups=catalog.deletable_groups,
        groups_by_family=groups_by_family,
        listx_tables=catalog.listx_tables,
        group_filter_display_names=catalog.group_filter_display_names,
        shortcut_targets=shortcut_targets,
    )


def trusted_public_config_tag_lookup_overlay(
    trusted_effects: PublicTrustedConfigEffects,
) -> TagLookupRuntimeOverlay:
    """Materialize trusted user-defined tags as a TagLookup request overlay."""

    from exifmodern.services.tag_lookup_runtime import (
        TagLookupRuntimeOverlay,
        TagLookupRuntimeOverlayEntry,
    )

    return TagLookupRuntimeOverlay(
        entries=tuple(
            TagLookupRuntimeOverlayEntry(
                source_config=tag.source_config,
                tag_name=tag.name,
                table_name=tag.table_name,
                tag_ids=(tag.tag_id,),
                writable=_trusted_config_tag_is_writable(tag),
            )
            for tag in trusted_effects.user_defined_tags
        )
    )


def public_trusted_config_materialization_contract() -> PublicTrustedConfigMaterializationContract:
    """Return the Batch 228 trusted config materialization contract."""

    return PublicTrustedConfigMaterializationContract(
        arbitrary_perl_config_execution="blocked",
        runtime_scope="request_scoped_overlay",
        public_global_table_mutation="blocked",
        trusted_tag_lookup_materialization=(
            "Trusted user-defined tag records are converted to immutable "
            "TagLookupRuntimeOverlayEntry values keyed by lower-cased tag name.",
            "Tag lookup resolution, wildcard matching, writable selection, and capability "
            "queries may consume the overlay for a single service/request instance.",
            "The generated TagLookup repository and public package globals are not mutated.",
        ),
        trusted_file_type_materialization=(
            "Trusted user-defined file type records are overlaid onto public listf/listr/"
            "listwf catalog sets for the catalog instance supplied by the caller.",
            "BaseType-backed trusted file types are treated as supported for request-scoped "
            "directory traversal; safe literal Magic-only records may be sniffed as "
            "recognized but are not treated as supported reader routes.",
            "Writable file-extension list materialization requires explicit trusted "
            "writable=True; inherited base-type writability is not guessed.",
        ),
        write_execution_policy=(
            "Trusted config user-defined tags resolve for lookup/list/read selection only.",
            "Write assignment/delete capability for trusted-config candidates is blocked by "
            "route class unless a future native writer explicitly owns that user-defined route.",
        ),
        evidence_ids=PUBLIC_CONFIG_MATERIALIZATION_EVIDENCE_IDS,
        remaining_blockers=(
            "arbitrary_non_empty_config_file_execution",
            "native_writer_routes_for_user_defined_tags",
            "inherited_file_type_writability_without_base_type_capability_model",
            "arbitrary_perl_regex_magic_pattern_sniffing",
            "arbitrary_use_plugin_loading",
        ),
    )


def public_trusted_config_frame_lifecycle_contract() -> PublicTrustedConfigFrameLifecycleContract:
    """Return the Batch 229 trusted config frame lifecycle contract."""

    return PublicTrustedConfigFrameLifecycleContract(
        arbitrary_perl_config_execution="blocked",
        frame_scope="execute_and_stay_open_command_frame",
        default_config_disable="suppresses_default_config_host_effects_before_frames",
        default_arguments_lifecycle="prepended_to_each_frame_after_config_handling",
        default_api_options_lifecycle="applied_to_each_frame_before_command_line_api_options",
        request_scoped_overlay_lifecycle="materialized_per_frame_without_global_mutation",
        config_in_argfile_policy="blocked_by_argfile_parser",
        evidence_ids=PUBLIC_CONFIG_FULL_FRAME_EVIDENCE_IDS,
        trust_boundary=(
            "Public runtime still does not read, require, eval, or execute Perl config files.",
            "A caller may provide typed trusted effects only after an external trusted host "
            "has isolated ExifTool's Perl-side package/global mutation.",
            "Typed default arguments and default API options are re-applied to every "
            "execute or stay-open command frame.",
            "Typed user-defined tag and file-type effects are consumed as request-scoped "
            "overlays for each frame; generated repositories and global tables are not mutated.",
            "An early empty -config disables default trusted effects for the bounded lifecycle.",
        ),
        remaining_blockers=(
            "arbitrary_non_empty_config_file_execution",
            "arbitrary_use_plugin_loading",
            "native_writer_routes_for_user_defined_tags",
            "trusted_magic_pattern_binary_file_sniffing",
        ),
    )


def public_trusted_extension_cluster_contract() -> PublicTrustedExtensionClusterContract:
    """Return the Batch 230 trusted config/plugin extension boundary."""

    return PublicTrustedExtensionClusterContract(
        magic_pattern_file_sniffing=(
            "BaseType-backed trusted file types are supported by request-scoped extension "
            "overlay for traversal and list output.",
            "Magic-only trusted file types are recognized-only; public runtime can sniff "
            "plain Latin-1 literal prefixes but does not promote a native reader route.",
            "Arbitrary Magic Perl regular expressions remain blocked because ExifTool "
            "matches them with Perl /^.../s against the binary buffer.",
        ),
        user_defined_tag_write_routes=(
            "Trusted user-defined tags participate in read/list/lookup overlays without "
            "mutating generated TagLookup tables.",
            "EXIF/GPS/IPTC/XMP/MIE and unknown trusted route classes are blocked for "
            "native writes unless a format writer explicitly owns that user-defined table.",
            "Existing generated XMP and JPEG scalar writers are not reused for user-defined "
            "tags because their schemas and binary table insertion rules are not global "
            "config mutations.",
        ),
        shortcut_and_default_argument_breadth=(
            "Trusted shortcuts are exposed in request-scoped public list catalog shortcut "
            "sets and expanded for read tag/exclusion tokens after built-in shortcut parsing.",
            "Trusted default command-line arguments are prepended after early -config "
            "handling and trusted default API options are converted to -api arguments "
            "before public read parsing.",
            "Default arguments containing -config remain rejected to avoid recursive "
            "arbitrary config execution through a trusted payload.",
        ),
        arbitrary_config_and_use_boundary=(
            "Empty -config remains the only safe public config form; non-empty config "
            "execution remains blocked unless supplied by an external trusted Perl host.",
            "-use MWG remains the only reviewed public -use marker; arbitrary -use MODULE "
            "loading remains blocked even when the module name is syntactically valid.",
            "The safe-expression VM is not a config/plugin host and must not execute Perl "
            "package/global side effects.",
        ),
        trust_boundary=(
            "Public runtime consumes typed trusted effects only.",
            "Generated package tables and process-global lookup state are not mutated.",
            "Recognized-only Magic matches do not imply supported native read or write routes.",
            "Native write execution for user-defined tags requires a future explicit "
            "format-local writer contract.",
        ),
        evidence_ids=PUBLIC_CONFIG_EXTENSION_CLUSTER_EVIDENCE_IDS,
        remaining_blockers=(
            "arbitrary_non_empty_config_file_execution",
            "arbitrary_use_plugin_loading",
            "arbitrary_perl_regex_magic_pattern_sniffing",
            "native_writer_execution_for_user_defined_tags",
            "inherited_file_type_writability_without_base_type_capability_model",
        ),
    )


def public_trusted_config_api_boundary_contract() -> PublicTrustedConfigApiBoundaryContract:
    """Return the Batch 231 trusted config/API public-read boundary."""

    return PublicTrustedConfigApiBoundaryContract(
        trusted_effect_lifecycle="typed_trusted_host_payload_to_api_arguments",
        source_backed_read_api_options=(
            "Charset",
            "Lang",
            "ListSep",
            "ListJoin",
            "ListItem",
            "MissingTagValue",
            "Duplicates",
            "PrintConv",
            "Unknown",
            "RequestAll",
            "Filter",
        ),
        arbitrary_config_execution="blocked",
        evidence_ids=PUBLIC_CONFIG_API_BOUNDARY_EVIDENCE_IDS,
        remaining_blockers=(
            "arbitrary_non_empty_config_file_execution",
            "arbitrary_use_plugin_loading",
            "api_options_requiring_unported_reader_state",
            "api_options_requiring_perl_callbacks_or_global_mutation",
        ),
    )


def public_config_plugin_release_decision_contract() -> PublicConfigPluginReleaseDecisionContract:
    """Return terminal release decisions for unsafe config/plugin seams.

    The public runtime owns typed effects after an external trust boundary. It
    intentionally does not become a Perl config/plugin host.
    """

    return PublicConfigPluginReleaseDecisionContract(
        family_id="charset_language_api_config",
        status="bounded_effects_closed_with_terminal_release_blockers",
        public_runtime_import_policy=(
            "Public runtime modules must not import developer audit tooling; config/plugin "
            "contracts live in public_interface as typed runtime boundaries only."
        ),
        bounded_effects_closed=(
            "default Charset/Lang/API options are parsed through public read API effects",
            "trusted default command-line arguments and default API options apply per "
            "execute/stay-open frame",
            "trusted shortcuts expand request-scoped read tag and exclusion tokens",
            "trusted user-defined tags and file types materialize as request-scoped overlays",
            "trusted Magic-only file types support plain Latin-1 literal-prefix sniffing",
            "-config empty-string disables default trusted effects before frame materialization",
            "-use MWG remains the only reviewed non-blocked plugin marker",
        ),
        release_decision_blockers=(
            PublicConfigPluginReleaseDecisionBlocker(
                code="arbitrary_non_empty_config_file_execution",
                surface="-config CFGFILE",
                status="external_trusted_host_required",
                exiftool_behavior=(
                    "ExifTool collects leading -config arguments before Image::ExifTool "
                    "loads, then Image::ExifTool.pm loads non-empty config files with "
                    "Perl require."
                ),
                public_runtime_decision=(
                    "Blocked in public runtime. A lifecycle-owning external trusted Perl "
                    "host may execute config files and return typed PublicTrustedConfigEffects."
                ),
                external_test_contract=(
                    "External host tests must prove isolated Perl execution, typed effect "
                    "serialization, empty -config disable behavior, and no mutation of "
                    "generated package globals."
                ),
                evidence_ids=PUBLIC_CONFIG_EARLY_LOAD_EVIDENCE_IDS,
            ),
            PublicConfigPluginReleaseDecisionBlocker(
                code="arbitrary_use_plugin_loading",
                surface="-use MODULE",
                status="external_trusted_host_required",
                exiftool_behavior=(
                    "ExifTool special-cases MWG and otherwise loads caller-selected Perl "
                    "modules through require/eval."
                ),
                public_runtime_decision=(
                    "Blocked except reviewed -use MWG. Arbitrary plugin loading is a "
                    "trusted-host or allowlist-review feature, not public runtime execution."
                ),
                external_test_contract=(
                    "External plugin tests must prove explicit module allowlisting, isolated "
                    "Perl side effects, frame persistence, and typed effect return values."
                ),
                evidence_ids=(
                    "public.config.use-module-load",
                    "public.config.execute-config-use-docs",
                ),
            ),
            PublicConfigPluginReleaseDecisionBlocker(
                code="arbitrary_perl_regex_magic_pattern_sniffing",
                surface="UserDefined::FileTypes Magic",
                status="not_public_runtime_feature",
                exiftool_behavior=(
                    "ExifTool stores config Magic as Perl regex fragments and matches them "
                    "against the binary prefix with /^.../s."
                ),
                public_runtime_decision=(
                    "Public runtime only sniffs plain Latin-1 literal prefixes. Perl regex "
                    "semantics are blocked instead of approximated with Python regex."
                ),
                external_test_contract=(
                    "External parity tests must execute real ExifTool Perl regex Magic in a "
                    "trusted host and compare recognized-only outcomes to typed host effects."
                ),
                evidence_ids=(
                    "public.config.user-file-types-docs",
                    "public.config.magic-regex-test",
                    "public.config.user-file-type-magic-merge",
                ),
            ),
            PublicConfigPluginReleaseDecisionBlocker(
                code="native_writer_execution_for_user_defined_tags",
                surface="writes to config-defined tags",
                status="blocked_until_native_writer_contract",
                exiftool_behavior=(
                    "ExifTool config may add writable tags to existing tables, including "
                    "table-specific write groups and code-backed conversion behavior."
                ),
                public_runtime_decision=(
                    "Trusted user-defined tags resolve for read/list/lookup overlays, but "
                    "write execution remains blocked until a format-local writer explicitly "
                    "owns the user-defined table route."
                ),
                external_test_contract=(
                    "Writer tests must be format-local and prove byte-level insertion, "
                    "WriteGroup handling, conversion behavior, and readback for each owned "
                    "user-defined route."
                ),
                evidence_ids=(
                    "public.config.user-tags-docs",
                    "public.config.writer-route",
                ),
            ),
            PublicConfigPluginReleaseDecisionBlocker(
                code="inherited_file_type_writability_without_base_type_capability_model",
                surface="UserDefined::FileTypes Writable inheritance",
                status="blocked_until_base_type_capability_model",
                exiftool_behavior=(
                    "ExifTool says BaseType-backed custom file types inherit writability "
                    "from the base type unless Writable is explicitly disabled."
                ),
                public_runtime_decision=(
                    "Public list/write surfaces only mark trusted file types writable when "
                    "the typed effect explicitly sets writable=True."
                ),
                external_test_contract=(
                    "Capability tests must prove base-type write ownership and inherited "
                    "extension routing before public runtime can expose implicit writability."
                ),
                evidence_ids=(
                    "public.config.user-file-types-docs",
                    "public.config.user-file-type-writable-inheritance",
                ),
            ),
        ),
        evidence_ids=PUBLIC_CONFIG_RELEASE_DECISION_EVIDENCE_IDS,
        focused_tests=(
            "tests/test_public_api_config_batch234.py",
            "tests/test_public_cli_config_batch230.py",
            "tests/test_public_api_config_batch230.py",
            "tests/test_public_runtime_boundaries.py",
        ),
    )


def _trusted_config_api_option_value_text(value: PublicTrustedConfigApiOptionValue) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _trusted_config_tag_is_writable(tag: PublicTrustedConfigUserDefinedTag) -> bool:
    return tag.writable is not False


def _trusted_magic_literal_bytes(pattern: str) -> bytes | None:
    if not pattern:
        return None
    if re.search(r"[\\.^$*+?{}\[\]|()]", pattern):
        return None
    try:
        return pattern.encode("latin-1")
    except UnicodeEncodeError:
        return None


def _split_trusted_shortcut_group_prefix(raw: str) -> tuple[str, str]:
    group_separator_index = raw.rfind(":")
    if group_separator_index < 0:
        return "", raw
    return raw[: group_separator_index + 1], raw[group_separator_index + 1 :]


def _split_trusted_shortcut_value_suffix(
    raw: str,
    *,
    remove_value_suffix: bool,
) -> tuple[str, str]:
    for marker in ("#",):
        if marker in raw:
            tag, suffix = raw.split(marker, 1)
            return tag, "" if remove_value_suffix else f"{marker}{suffix}"
    return raw, ""


def _casefold_sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(frozenset(values), key=str.casefold))


def public_config_defined_effects_contract() -> PublicConfigDefinedEffectsContract:
    """Return structured blockers/effect shapes for config-defined behavior."""

    return PublicConfigDefinedEffectsContract(
        arbitrary_config_execution="blocked",
        default_arguments_insertion="before_all_non_config_arguments",
        shortcuts_without_host_execution="not_representable",
        default_arguments_without_host_execution="not_representable",
        effect_boundaries=(
            PublicConfigDefinedEffectBoundary(
                surface="user_defined_shortcuts",
                exiftool_storage="%Image::ExifTool::UserDefined::Shortcuts",
                exiftool_effect=(
                    "Adds shortcut names that expand into one or more requested/excluded tags."
                ),
                public_runtime_contract="trusted_host_return_only",
                trusted_host_payload=(
                    "tuple[PublicTrustedConfigShortcut, ...] with plain shortcut names and "
                    "plain string tag targets"
                ),
                blocker_code="config_shortcuts_require_perl_config_host",
                blocker_message=(
                    "Config-defined shortcuts are assigned by a Perl config file loaded with "
                    "require; public ExifModern can consume a trusted host's typed shortcut "
                    "map but must not derive it by executing arbitrary config Perl."
                ),
                evidence_ids=(
                    "public.config.shortcuts-docs",
                    "public.config.shortcut-expansion",
                    "public.config.config-file-load",
                ),
            ),
            PublicConfigDefinedEffectBoundary(
                surface="user_defined_command_line_arguments",
                exiftool_storage="@Image::ExifTool::UserDefined::Arguments",
                exiftool_effect=(
                    "Prepends default command-line arguments before normal option parsing, "
                    "after early -config arguments have been consumed."
                ),
                public_runtime_contract="trusted_host_return_only",
                trusted_host_payload=(
                    "PublicTrustedConfigDefaultArguments containing source_config and a "
                    "tuple[str, ...] of already-tokenized arguments"
                ),
                blocker_code="config_default_arguments_require_perl_config_host",
                blocker_message=(
                    "Config-defined default arguments are populated by executing the Perl "
                    "config file; public ExifModern can apply already-tokenized trusted "
                    "arguments but must not run arbitrary config Perl to discover them."
                ),
                evidence_ids=(
                    "public.config.early-config-collection",
                    "public.config.default-arguments-insert",
                    "public.config.default-arguments-docs",
                    "public.config.config-file-load",
                ),
            ),
            PublicConfigDefinedEffectBoundary(
                surface="user_defined_tags",
                exiftool_storage="%Image::ExifTool::UserDefined",
                exiftool_effect=(
                    "Adds table-specific tag definitions, including code-backed Composite "
                    "ValueConv/PrintConv definitions."
                ),
                public_runtime_contract="blocked_until_trusted_host_effects",
                trusted_host_payload=(
                    "tuple[PublicTrustedConfigUserDefinedTag, ...] with table name, tag ID, "
                    "plain tag name, Writable value, and optional WriteGroup"
                ),
                blocker_code="config_user_tags_require_perl_config_host",
                blocker_message=(
                    "User-defined tags may include Perl code references and conversion "
                    "expressions, so public runtime cannot safely materialize them from a "
                    "config file without a trusted host."
                ),
                evidence_ids=(
                    "public.config.user-tags-docs",
                    "public.config.config-file-load",
                ),
            ),
            PublicConfigDefinedEffectBoundary(
                surface="user_defined_file_types",
                exiftool_storage="%Image::ExifTool::UserDefined::FileTypes",
                exiftool_effect="Adds user-defined file type recognition records.",
                public_runtime_contract="blocked_until_trusted_host_effects",
                trusted_host_payload=(
                    "tuple[PublicTrustedConfigUserDefinedFileType, ...] with extension, "
                    "BaseType/Magic/Description, MIMEType, and optional Writable flag"
                ),
                blocker_code="config_file_types_require_perl_config_host",
                blocker_message=(
                    "User-defined file types are config-populated global Perl state; public "
                    "runtime must not execute config Perl to mutate file type recognition."
                ),
                evidence_ids=(
                    "public.config.user-file-types-docs",
                    "public.config.user-file-type-merge",
                ),
            ),
            PublicConfigDefinedEffectBoundary(
                surface="default_api_options",
                exiftool_storage="%Image::ExifTool::UserDefined::Options",
                exiftool_effect="Sets default ExifTool API options on new ExifTool instances.",
                public_runtime_contract="blocked_until_trusted_host_effects",
                trusted_host_payload="tuple[PublicTrustedConfigDefaultApiOption, ...]",
                blocker_code="config_default_api_options_require_perl_config_host",
                blocker_message=(
                    "Default API options are global config state copied into ExifTool "
                    "instances; public runtime must not run arbitrary config Perl to set them."
                ),
                evidence_ids=(
                    "public.config.user-options-instance-copy",
                    "public.config.default-api-options-docs",
                ),
            ),
        ),
    )


def public_config_plugin_vm_boundary_contract() -> PublicConfigPluginVmBoundaryContract:
    """Return the source-backed config/plugin execution boundary.

    The existing VM is for bounded safe expressions. ExifTool config files and
    non-MWG plug-ins mutate global package state and load Perl modules, so the
    public interface keeps only reviewed non-executing markers here.
    """

    return PublicConfigPluginVmBoundaryContract(
        safe_config_forms=('-config ""',),
        safe_use_modules=("MWG",),
        safe_source_backed_expansions=(
            "After an empty -config disables configuration loading, subsequent -config "
            "CFGFILE tokens are consumed as suppressed filenames and are not loaded.",
            "-use MWG is a reviewed built-in module marker; arbitrary require/eval module "
            "loading is not part of the public safe subset.",
        ),
        trusted_vm_execution="not_safe_expression_vm_backed",
        trusted_host_contract=(
            "Config/plugin execution is not routed through the safe-expression VM.",
            "A future trusted host must isolate Perl package/global side effects from the "
            "public runtime and return typed effects only.",
            "A future config host must model ExifTool's pre-Image::ExifTool load order, "
            "default-config search path, user-defined tags, default API options, and "
            "user-defined command-line arguments before it can load non-empty CFGFILEs.",
            "A future plugin host must be allowlist reviewed; arbitrary caller-selected "
            "Perl require/eval remains blocked even if the module name is syntactically valid.",
        ),
        arbitrary_config_blocker=(
            "ExifTool collects -config before Image::ExifTool loads; non-empty "
            "configuration files may define user tags, shortcuts, file types, default "
            "options, command-line arguments, and Perl code, so executing them requires "
            "a trusted host Perl/config boundary rather than the safe-expression VM."
        ),
        arbitrary_plugin_blocker=(
            "ExifTool special-cases -use MWG, but other -use modules are loaded with "
            "Perl require/eval and remain active across -execute frames; public "
            "ExifModern must not execute arbitrary Perl module side effects."
        ),
        evidence_ids=PUBLIC_CONFIG_VM_BOUNDARY_EVIDENCE_IDS,
        remaining_blockers=(
            "non_empty_config_file_loading",
            "arbitrary_use_plugin_loading",
            "config_defined_user_tags_shortcuts_file_types_and_defaults",
            "config_defined_command_line_arguments_before_public_parse",
            "host_perl_side_effect_lifecycle_across_execute_frames",
        ),
    )


def parse_safe_public_config_option(
    option: str,
    args: Sequence[str],
    index: int,
    *,
    default_config_already_disabled: bool,
) -> PublicSafeConfigOptionEffect:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError("Expecting file name for -config option")
    config_path = args[value_index]
    if config_path == "":
        return PublicSafeConfigOptionEffect(disable_default_config=True)
    if default_config_already_disabled:
        return PublicSafeConfigOptionEffect(suppressed_config_file=config_path)
    raise argparse.ArgumentTypeError(public_config_deferred_message())


def parse_safe_public_use_option(
    option: str,
    args: Sequence[str],
    index: int,
) -> bool:
    module = _parse_public_use_module(option, args, index)
    if module.lower() == "mwg":
        return True
    if re.search(r"[^\w:]", module):
        raise argparse.ArgumentTypeError(f"Invalid module name: {module}")
    raise argparse.ArgumentTypeError(public_use_deferred_message())


def public_config_deferred_message() -> str:
    return (
        "public -config Perl configuration loading is intentionally not implemented "
        "and cannot be represented by the existing safe-expression VM; "
        "source ids public.config.early-config-collection, "
        "public.config.config-file-load, and public.config.config-docs cover the "
        "early load order, empty CFGFILE disables the default config behavior, "
        "and why arbitrary config files may define tags and load code"
    )


def public_use_deferred_message() -> str:
    return (
        "public Perl plug-in loading for -use is intentionally not implemented; "
        "source ids public.config.use-module-load and public.config.use-docs cover "
        "the reviewed built-in -use MWG marker, accepts the reviewed built-in -use "
        "MWG marker, blocks arbitrary Perl module loading, and frame-persistent "
        "module effects"
    )


def _parse_public_use_module(
    option: str,
    args: Sequence[str],
    index: int,
) -> str:
    value_index = index + 1
    if value_index >= len(args):
        raise argparse.ArgumentTypeError("Expecting module name for -use option")
    module = args[value_index]
    if not module or module.startswith("-"):
        raise argparse.ArgumentTypeError("Expecting module name for -use option")
    return module
