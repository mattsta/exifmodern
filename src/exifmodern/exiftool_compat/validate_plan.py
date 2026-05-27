"""Source-grounded planning helpers for ExifTool Validate.pm behavior."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type ValidationScalar = str | int | float | bool | bytes | None
type ValidationSeverity = Literal["error", "warning", "minor_warning"]
type ValidationCategory = Literal[
    "emission",
    "format",
    "invalid_value",
    "not_allowed",
    "ordering",
    "required",
    "unsupported",
    "version",
    "wrong_ifd",
]
type ValidationStatus = Literal["planned", "unsupported"]
type ValidationRuleKind = Literal[
    "defined",
    "must_not_exist",
    "regex",
    "numeric_choices",
    "optional_regex",
]
type ValidateEvidenceId = str


@dataclass(frozen=True)
class ValidateGate:
    code: str
    category: ValidationCategory
    message: str
    source_symbol: str


@dataclass(frozen=True)
class ValidateAction:
    kind: str
    source_symbol: str
    detail: str


@dataclass(frozen=True)
class ValidateTag:
    group: str
    tag_id: int
    name: str
    value: ValidationScalar
    wrong_format: bool = False
    g3: bool = False


@dataclass(frozen=True)
class ValidateExifEntry:
    ifd: str
    tag_id: int
    name: str
    count: int
    format_name: str
    writable: str | None = None
    write_group: str | None = None
    unknown: bool = False


@dataclass(frozen=True)
class ValidateIssue:
    severity: ValidationSeverity
    category: ValidationCategory
    message: str
    group: str | None
    tag_id: int | None
    tag_name: str | None
    minor: bool
    source_symbol: str


@dataclass(frozen=True)
class ValidateSummary:
    errors: int
    warnings: int
    minor_warnings: int

    @property
    def validate_value(self) -> str:
        return f"{self.errors} {self.warnings} {self.minor_warnings}"


@dataclass(frozen=True)
class ValidatePlan:
    file_type: str
    status: ValidationStatus
    tags: tuple[ValidateTag, ...]
    exif_entries: tuple[ValidateExifEntry, ...]
    issues: tuple[ValidateIssue, ...]
    blockers: tuple[ValidateGate, ...]
    output_emission_gates: tuple[ValidateGate, ...]
    actions: tuple[ValidateAction, ...]
    evidence_ids: tuple[ValidateEvidenceId, ...]
    can_mutate_metadata: bool
    can_emit_output: bool
    summary: ValidateSummary

    def emit(self) -> tuple[ValidateIssue, ...]:
        if not self.can_emit_output:
            codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Validate plan output is gated: {codes}")
        return self.issues


@dataclass(frozen=True)
class _ValueRule:
    group: str
    tag_id: int
    name: str
    kind: ValidationRuleKind
    pattern: str = ""
    choices: tuple[int, ...] = ()


@dataclass(frozen=True)
class _VersionRule:
    group: str
    version_tag: str
    tag_id: int
    name: str
    required_version: int


_VALIDATE_EVIDENCE_IDS = (
    "exiftool_compat.validate.exif_spec",
    "exiftool_compat.validate.gps_version",
    "exiftool_compat.validate.version_check",
    "exiftool_compat.validate.valid_value",
    "exiftool_compat.validate.validate_exif",
    "exiftool_compat.validate.finish_validate",
    "exiftool_compat.validate.validate_info",
)
_SUPPORTED_FILE_TYPES = frozenset(("JPEG", "TIFF"))
_GPS_VERSION_PATTERN = re.compile(r"^\d \d \d \d$")
_EXIF_VERSION_PATTERN = re.compile(r"^\d{4}$")
_GPS_PROCESSING_PATTERN = re.compile(r"^(GPS|CELLID|WLAN|MANUAL)$")
_YCBC_POSITION_PATTERN = re.compile(r"^[12]$")
_TIFF_PHOTOMETRIC_PATTERN = re.compile(r"^[0123]$")
_TIFF_RESOLUTION_UNIT_PATTERN = re.compile(r"^[123]$")
_STD_FORMATS = {
    ("IFD0", 0x0100): "int(16|32)u",
    ("IFD0", 0x0101): "int(16|32)u",
    ("IFD0", 0x0111): "int(16|32)u",
    ("IFD0", 0x0116): "int(16|32)u",
    ("IFD0", 0x0117): "int(16|32)u",
    ("IFD0", 0x0128): "int16u",
    ("ExifIFD", 0xA002): "int(16|32)u",
    ("ExifIFD", 0xA003): "int(16|32)u",
    ("IFD", 0x010E): "string|utf8",
    ("IFD", 0x010F): "string|utf8",
    ("IFD", 0x0110): "string|utf8",
}
_IFD_STD_ANY = frozenset(0x0100 + offset for offset in (0, 1, 0xE, 0xF, 0x10, 0x11, 0x16, 0x17))
_OTHER_SPEC_ALL_FILE_TYPES = frozenset(("RW2", "RWL", "RAF", "DCR", "KDC", "JXR"))
_OTHER_SPEC_TAGS = {
    "CR2": frozenset((0xC5D8, 0xC5D9, 0xC5E0, 0xC640, 0xC6DC, 0xC6DD)),
    "NEF": frozenset((0x9216, 0x9217)),
    "DNG": frozenset((0x882A, 0x9211, 0x9216)),
    "SRW": frozenset((0xA010, 0xA011, 0xA101, 0xA102)),
    "NRW": frozenset((0x9216, 0x9217)),
    "X3F": frozenset((0xA500,)),
}
_OTHER_SPEC_IFDS = frozenset(("CameraIFD",))

_JPEG_RULES = (
    _ValueRule("IFD0", 0x0100, "ImageWidth", "must_not_exist"),
    _ValueRule("IFD0", 0x0101, "ImageLength", "must_not_exist"),
    _ValueRule("IFD0", 0x0102, "BitsPerSample", "must_not_exist"),
    _ValueRule("IFD0", 0x0103, "Compression", "must_not_exist"),
    _ValueRule("IFD0", 0x0106, "PhotometricInterpretation", "must_not_exist"),
    _ValueRule("IFD0", 0x0111, "StripOffsets", "must_not_exist"),
    _ValueRule("IFD0", 0x0115, "SamplesPerPixel", "must_not_exist"),
    _ValueRule("IFD0", 0x0116, "RowsPerStrip", "must_not_exist"),
    _ValueRule("IFD0", 0x0117, "StripByteCounts", "must_not_exist"),
    _ValueRule("IFD0", 0x011C, "PlanarConfiguration", "must_not_exist"),
    _ValueRule("IFD0", 0x0201, "JPEGInterchangeFormat", "must_not_exist"),
    _ValueRule("IFD0", 0x0202, "JPEGInterchangeFormatLength", "must_not_exist"),
    _ValueRule("IFD0", 0x0212, "YCbCrSubSampling", "must_not_exist"),
    _ValueRule("IFD0", 0x0213, "YCbCrPositioning", "regex", pattern=r"^[12]$"),
    _ValueRule("IFD1", 0x0103, "Compression", "numeric_choices", choices=(6,)),
    _ValueRule("IFD1", 0x011A, "XResolution", "defined"),
    _ValueRule("IFD1", 0x011B, "YResolution", "defined"),
    _ValueRule("IFD1", 0x0128, "ResolutionUnit", "regex", pattern=r"^[123]$"),
    _ValueRule("IFD1", 0x0201, "JPEGInterchangeFormat", "defined"),
    _ValueRule("IFD1", 0x0202, "JPEGInterchangeFormatLength", "defined"),
    _ValueRule("ExifIFD", 0x9000, "ExifVersion", "regex", pattern=r"^\d{4}$"),
    _ValueRule("ExifIFD", 0x9101, "ComponentsConfiguration", "defined"),
    _ValueRule("ExifIFD", 0xA001, "ColorSpace", "numeric_choices", choices=(1, 0xFFFF)),
    _ValueRule("ExifIFD", 0xA002, "PixelXDimension", "defined"),
    _ValueRule("ExifIFD", 0xA003, "PixelYDimension", "defined"),
    _ValueRule("GPS", 0x0000, "GPSVersionID", "regex", pattern=r"^\d \d \d \d$"),
    _ValueRule(
        "GPS",
        0x001B,
        "GPSProcessingMethod",
        "optional_regex",
        pattern=r"^(GPS|CELLID|WLAN|MANUAL)$",
    ),
)
_TIFF_RULES = (
    _ValueRule("IFD0", 0x0100, "ImageWidth", "defined"),
    _ValueRule("IFD0", 0x0101, "ImageLength", "defined"),
    _ValueRule("IFD0", 0x0106, "PhotometricInterpretation", "regex", pattern=r"^[0123]$"),
    _ValueRule("IFD0", 0x0111, "StripOffsets", "defined"),
    _ValueRule("IFD0", 0x0116, "RowsPerStrip", "defined"),
    _ValueRule("IFD0", 0x0117, "StripByteCounts", "defined"),
    _ValueRule("IFD0", 0x011A, "XResolution", "defined"),
    _ValueRule("IFD0", 0x011B, "YResolution", "defined"),
    _ValueRule("IFD0", 0x0128, "ResolutionUnit", "optional_regex", pattern=r"^[123]$"),
    _ValueRule("IFD0", 0x0201, "JPEGInterchangeFormat", "must_not_exist"),
    _ValueRule("IFD0", 0x0202, "JPEGInterchangeFormatLength", "must_not_exist"),
    _ValueRule("ExifIFD", 0x9000, "ExifVersion", "defined"),
    _ValueRule("ExifIFD", 0x9101, "ComponentsConfiguration", "must_not_exist"),
    _ValueRule("ExifIFD", 0x9102, "CompressedBitsPerPixel", "must_not_exist"),
    _ValueRule("ExifIFD", 0xA000, "FlashpixVersion", "defined"),
    _ValueRule("ExifIFD", 0xA001, "ColorSpace", "numeric_choices", choices=(1, 0xFFFF)),
    _ValueRule("ExifIFD", 0xA002, "PixelXDimension", "must_not_exist"),
    _ValueRule("ExifIFD", 0xA003, "PixelYDimension", "must_not_exist"),
    _ValueRule("InteropIFD", 0x0001, "InteropIndex", "must_not_exist"),
    _ValueRule("GPS", 0x0000, "GPSVersionID", "regex", pattern=r"^\d \d \d \d$"),
    _ValueRule(
        "GPS",
        0x001B,
        "GPSProcessingMethod",
        "regex",
        pattern=r"^(GPS|CELLID|WLAN|MANUAL)$",
    ),
)
_VALID_VALUE_RULES = {
    "JPEG": _JPEG_RULES,
    "TIFF": _TIFF_RULES,
}
_VERSION_RULES = (
    _VersionRule("ExifIFD", "ExifVersion", 0xA432, "LensSpecification", 230),
    _VersionRule("ExifIFD", "ExifVersion", 0xA436, "ImageTitle", 300),
    _VersionRule("InteropIFD", "ExifVersion", 0xA432, "LensSpecification", 230),
    _VersionRule("GPS", "GPSVersionID", 0x001B, "GPSProcessingMethod", 2200),
    _VersionRule("GPS", "GPSVersionID", 0x001F, "HorizPositioningError", 2300),
)

__all__ = (
    "ValidateAction",
    "ValidateExifEntry",
    "ValidateGate",
    "ValidateIssue",
    "ValidatePlan",
    "ValidateSummary",
    "ValidateTag",
    "build_validate_plan",
)


def build_validate_plan(
    file_type: str,
    tags: tuple[ValidateTag, ...] = (),
    exif_entries: tuple[ValidateExifEntry, ...] = (),
    found_dirs: tuple[str, ...] = (),
    allow_output_emission: bool = False,
    initial_error_count: int = 0,
) -> ValidatePlan:
    normalized_file_type = file_type.upper()
    issues: list[ValidateIssue] = []
    blockers: list[ValidateGate] = []
    gates: list[ValidateGate] = []
    actions: list[ValidateAction] = []

    if normalized_file_type not in _SUPPORTED_FILE_TYPES:
        gate = ValidateGate(
            code="unsupported_validate_file_type",
            category="unsupported",
            message=f"Validate.pm valid-value planning is limited to JPEG/TIFF, not {file_type}.",
            source_symbol="FinishValidate",
        )
        blockers.append(gate)
        gates.append(gate)
        actions.append(
            ValidateAction(
                kind="block_unsupported_validate_file_type",
                source_symbol="FinishValidate",
                detail=normalized_file_type,
            )
        )
    else:
        issues.extend(_finish_validate_issues(normalized_file_type, tags, found_dirs, actions))
        issues.extend(_validate_exif_issues(normalized_file_type, exif_entries, actions))

    if not allow_output_emission:
        gates.append(
            ValidateGate(
                code="non_mutating_plan_requires_explicit_emission",
                category="emission",
                message="Validate planning is non-mutating and requires explicit output emission.",
                source_symbol="%validateInfo",
            )
        )

    summary = _summarize(issues, initial_error_count)
    return ValidatePlan(
        file_type=normalized_file_type,
        status="unsupported" if blockers else "planned",
        tags=tags,
        exif_entries=exif_entries,
        issues=tuple(issues),
        blockers=tuple(blockers),
        output_emission_gates=tuple(gates),
        actions=tuple(actions),
        evidence_ids=_VALIDATE_EVIDENCE_IDS,
        can_mutate_metadata=False,
        can_emit_output=allow_output_emission and not gates,
        summary=summary,
    )


def _finish_validate_issues(
    file_type: str,
    tags: tuple[ValidateTag, ...],
    found_dirs: tuple[str, ...],
    actions: list[ValidateAction],
) -> tuple[ValidateIssue, ...]:
    found_groups = frozenset(found_dirs) | frozenset(tag.group for tag in tags if not tag.g3)
    values = _tag_values_by_group(tags)
    info = _tag_info_by_group(tags)
    issues: list[ValidateIssue] = []

    for version_rule in _VERSION_RULES:
        if version_rule.group not in found_groups:
            continue
        version = _version_value(version_rule.version_tag, values)
        tag_value = values.get(version_rule.group, {}).get(version_rule.tag_id)
        if tag_value is None or version is None or version >= version_rule.required_version:
            continue
        message = _version_message(version_rule)
        issues.append(
            _issue(
                "warning",
                "version",
                message,
                version_rule.group,
                version_rule.tag_id,
                _tag_name(info, version_rule.group, version_rule.tag_id, version_rule.name),
                False,
                "%verCheck",
            )
        )
        actions.append(ValidateAction("route_version_check", "%verCheck", message))

    for value_rule in _VALID_VALUE_RULES[file_type]:
        if value_rule.group not in found_groups:
            continue
        value = values.get(value_rule.group, {}).get(value_rule.tag_id)
        if _rule_passes(value_rule, value):
            continue
        known_name = _tag_name(info, value_rule.group, value_rule.tag_id, value_rule.name)
        if _is_wrong_format_suppressed(tags, value_rule.group, value_rule.tag_id, known_name):
            continue
        if value_rule.kind == "must_not_exist":
            message = (
                f"{value_rule.group} tag 0x{value_rule.tag_id:04x} "
                f"{known_name} is not allowed in {file_type}"
            )
            issues.append(
                _issue(
                    "minor_warning",
                    "not_allowed",
                    message,
                    value_rule.group,
                    value_rule.tag_id,
                    known_name,
                    True,
                    "%validValue",
                )
            )
            actions.append(ValidateAction("route_not_allowed_value", "%validValue", message))
            continue
        prefix = "Invalid value for" if value is not None else f"Missing required {file_type}"
        message = f"{prefix} {value_rule.group} tag 0x{value_rule.tag_id:04x} {known_name}"
        category: ValidationCategory = "invalid_value" if value is not None else "required"
        issues.append(
            _issue(
                "warning",
                category,
                message,
                value_rule.group,
                value_rule.tag_id,
                known_name,
                False,
                "%validValue",
            )
        )
        actions.append(ValidateAction("route_valid_value_check", "%validValue", message))

    return tuple(issues)


def _validate_exif_issues(
    file_type: str,
    entries: tuple[ValidateExifEntry, ...],
    actions: list[ValidateAction],
) -> tuple[ValidateIssue, ...]:
    issues: list[ValidateIssue] = []
    last_by_ifd: dict[str, int] = {}
    for entry in entries:
        last_tag = last_by_ifd.get(entry.ifd)
        if last_tag is not None and entry.tag_id <= last_tag:
            message = f"Entries in {entry.ifd} are out of order"
            issues.append(
                _issue(
                    "warning",
                    "ordering",
                    message,
                    entry.ifd,
                    entry.tag_id,
                    entry.name,
                    False,
                    "ValidateExif",
                )
            )
            actions.append(ValidateAction("route_entry_order_check", "ValidateExif", message))
        last_by_ifd[entry.ifd] = entry.tag_id

        if entry.write_group and entry.write_group not in (entry.ifd, "All"):
            message = (
                f"Wrong IFD for 0x{entry.tag_id:04x} {entry.name} "
                f"(should be {entry.write_group} not {entry.ifd})"
            )
            issues.append(
                _issue(
                    "warning",
                    "wrong_ifd",
                    message,
                    entry.ifd,
                    entry.tag_id,
                    entry.name,
                    False,
                    "ValidateExif",
                )
            )
            actions.append(ValidateAction("route_wrong_ifd_check", "ValidateExif", message))

        standard_format = _standard_format_for(entry)
        if standard_format and not _format_matches(standard_format, entry.format_name):
            message = (
                f"Non-standard format ({entry.format_name}) for "
                f"{entry.ifd} 0x{entry.tag_id:04x} {entry.name}"
            )
            issues.append(
                _issue(
                    "warning",
                    "format",
                    message,
                    entry.ifd,
                    entry.tag_id,
                    entry.name,
                    False,
                    "ValidateExif",
                )
            )
            actions.append(ValidateAction("route_standard_format_check", "ValidateExif", message))
        elif _is_unknown_nonstandard_tag(file_type, entry):
            message = f"Unknown {entry.ifd} tag 0x{entry.tag_id:04x}"
            issues.append(
                _issue(
                    "minor_warning",
                    "unsupported",
                    message,
                    entry.ifd,
                    entry.tag_id,
                    entry.name,
                    True,
                    "ValidateExif",
                )
            )
            actions.append(ValidateAction("route_unknown_tag_check", "ValidateExif", message))

    return tuple(issues)


def _tag_values_by_group(tags: tuple[ValidateTag, ...]) -> dict[str, dict[int, ValidationScalar]]:
    values: dict[str, dict[int, ValidationScalar]] = {}
    for tag in tags:
        if tag.g3:
            continue
        values.setdefault(tag.group, {})[tag.tag_id] = tag.value
    return values


def _tag_info_by_group(tags: tuple[ValidateTag, ...]) -> dict[str, dict[int, str]]:
    info: dict[str, dict[int, str]] = {}
    for tag in tags:
        if tag.g3:
            continue
        info.setdefault(tag.group, {})[tag.tag_id] = tag.name
    return info


def _version_value(
    version_tag: str,
    values: Mapping[str, Mapping[int, ValidationScalar]],
) -> int | None:
    if version_tag == "ExifVersion":
        for group in ("ExifIFD", "InteropIFD"):
            value = values.get(group, {}).get(0x9000)
            version = _digits_version(value, 4)
            if version is not None:
                return version
        return None
    value = values.get("GPS", {}).get(0x0000)
    return _digits_version(value, 4)


def _digits_version(value: ValidationScalar, expected_digits: int) -> int | None:
    if value is None:
        return None
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) != expected_digits:
        return None
    return int(digits)


def _version_message(rule: _VersionRule) -> str:
    if rule.version_tag == "GPSVersionID":
        version_text = str(rule.required_version)
        formatted_version = (
            f"{version_text[0]}.{version_text[1]}.{version_text[2]}.{version_text[3:]}"
        )
    else:
        formatted_version = f"{rule.required_version:04d}"
    return (
        f"{rule.group} tag 0x{rule.tag_id:04x} {rule.name} requires "
        f"{rule.version_tag} {formatted_version} or higher"
    )


def _rule_passes(rule: _ValueRule, value: ValidationScalar) -> bool:
    if rule.kind == "defined":
        return value is not None
    if rule.kind == "must_not_exist":
        return value is None
    if rule.kind == "regex":
        return value is not None and re.fullmatch(rule.pattern, str(value)) is not None
    if rule.kind == "optional_regex":
        return value is None or re.fullmatch(rule.pattern, str(value)) is not None
    return _numeric_value(value) in rule.choices


def _numeric_value(value: ValidationScalar) -> int | None:
    if isinstance(value, bool) or value is None or isinstance(value, bytes):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_wrong_format_suppressed(
    tags: tuple[ValidateTag, ...],
    group: str,
    tag_id: int,
    name: str,
) -> bool:
    for tag in tags:
        if tag.group == group and tag.tag_id == tag_id and tag.name == name:
            return tag.wrong_format
    return False


def _tag_name(
    info: Mapping[str, Mapping[int, str]],
    group: str,
    tag_id: int,
    fallback: str,
) -> str:
    return info.get(group, {}).get(tag_id, fallback)


def _standard_format_for(entry: ValidateExifEntry) -> str:
    if (entry.ifd, entry.tag_id) in _STD_FORMATS:
        return _STD_FORMATS[(entry.ifd, entry.tag_id)]
    return _STD_FORMATS.get(("IFD", entry.tag_id), "")


def _format_matches(expected: str, actual: str) -> bool:
    if expected == "int(16|32)u":
        return actual in ("int16u", "int32u")
    if expected == "string|utf8":
        return actual in ("string", "utf8")
    return actual == expected


def _is_unknown_nonstandard_tag(file_type: str, entry: ValidateExifEntry) -> bool:
    if not entry.unknown:
        return False
    if entry.ifd in _OTHER_SPEC_IFDS:
        return False
    if file_type in _OTHER_SPEC_ALL_FILE_TYPES:
        return False
    return entry.tag_id not in _OTHER_SPEC_TAGS.get(file_type, frozenset())


def _issue(
    severity: ValidationSeverity,
    category: ValidationCategory,
    message: str,
    group: str | None,
    tag_id: int | None,
    tag_name: str | None,
    minor: bool,
    source_symbol: str,
) -> ValidateIssue:
    return ValidateIssue(
        severity=severity,
        category=category,
        message=message,
        group=group,
        tag_id=tag_id,
        tag_name=tag_name,
        minor=minor,
        source_symbol=source_symbol,
    )


def _summarize(
    issues: tuple[ValidateIssue, ...] | list[ValidateIssue],
    initial_errors: int,
) -> ValidateSummary:
    warnings = sum(1 for issue in issues if issue.severity in ("warning", "minor_warning"))
    minor_warnings = sum(1 for issue in issues if issue.minor)
    errors = initial_errors + sum(1 for issue in issues if issue.severity == "error")
    return ValidateSummary(errors=errors, warnings=warnings, minor_warnings=minor_warnings)
