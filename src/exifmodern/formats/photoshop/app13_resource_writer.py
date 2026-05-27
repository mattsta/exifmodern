"""Source-backed Photoshop APP13 Image Resource Block writer primitives."""

from __future__ import annotations

import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.iptc.dataset_writer import apply_iptc_application_write_plan
from exifmodern.formats.iptc.write_plan import (
    IptcApplicationWritePlan,
    coalesce_iptc_application_steps,
    iptc_application_tag_spec,
    upsert_text_step,
)
from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceEntry,
    encode_image_resource_section,
    parse_image_resource_blocks,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceMutation,
    apply_image_resource_entry_mutations,
)

PHOTOSHOP_RESOURCE_ID_COPYRIGHT_FLAG = 0x040A
PHOTOSHOP_RESOURCE_ID_URL = 0x040B
PHOTOSHOP_RESOURCE_ID_GLOBAL_ANGLE = 0x040D
PHOTOSHOP_RESOURCE_ID_GLOBAL_ALTITUDE = 0x0419
PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST = 0x0425
PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO = 0x03ED
PHOTOSHOP_RESOURCE_ID_IPTC_DATA = 0x0404
PHOTOSHOP_RESOURCE_ID_JPEG_QUALITY = 0x0406
PHOTOSHOP_RESOURCE_ID_VERSION_INFO = 0x0421
PHOTOSHOP_RESOURCE_ID_PRINT_SCALE_INFO = 0x0426
PHOTOSHOP_RESOURCE_ID_PIXEL_INFO = 0x0428

UINT32_MAX = 0xFFFFFFFF
_HEXADECIMAL_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{32}$")

type PhotoshopApp13PatchKind = Literal[
    "resolution",
    "jpeg_quality",
    "print_scale",
    "version_info",
    "iptc_digest",
    "pixel_info",
]
type PhotoshopIptcDigestMode = Literal["new", "old"]
type PhotoshopApp13AssignmentBlockerReason = Literal[
    "not_photoshop_app13_assignment",
    "url_list_no_valueconvinv",
    "thumbnail_binary_payload",
    "unsupported_photoshop_app13_tag",
]


@dataclass(frozen=True)
class PhotoshopApp13ResourcePatch:
    kind: PhotoshopApp13PatchKind
    field_name: str
    value: str


@dataclass(frozen=True)
class PhotoshopApp13ResourceWriteStep:
    tag_name: str
    resource_id: int
    data: bytes | None = None
    patch: PhotoshopApp13ResourcePatch | None = None


@dataclass(frozen=True)
class PhotoshopApp13ResourceWritePlan:
    steps: tuple[PhotoshopApp13ResourceWriteStep, ...]
    iptc_plan: IptcApplicationWritePlan | None = None


def build_photoshop_app13_resource_write_plan(
    assignments: Sequence[tuple[str, str]],
    list_separator: str | None = None,
) -> PhotoshopApp13ResourceWritePlan | None:
    """Build an APP13 IRB plan for source-backed simple Photoshop assignments."""

    steps: list[PhotoshopApp13ResourceWriteStep] = []
    direct_step_indexes: dict[int, int] = {}
    patch_resource_ids: set[int] = set()
    iptc_steps = []
    has_iptc_digest_mode_step = False
    for tag, value in assignments:
        step = photoshop_app13_resource_write_step(tag, value)
        if step is not None:
            if step.patch is not None and step.patch.kind == "iptc_digest":
                has_iptc_digest_mode_step = True
            if step.data is not None:
                if step.resource_id in patch_resource_ids:
                    return None
                existing_index = direct_step_indexes.get(step.resource_id)
                if existing_index is None:
                    direct_step_indexes[step.resource_id] = len(steps)
                    steps.append(step)
                else:
                    steps[existing_index] = step
                continue
            if step.resource_id in direct_step_indexes:
                return None
            patch_resource_ids.add(step.resource_id)
            steps.append(step)
            continue

        group, tag_name = public_write_tag_parts(tag)
        if group != "iptc" or iptc_application_tag_spec(tag_name) is None:
            return None
        values = (value,) if list_separator is None else tuple(value.split(list_separator))
        try:
            iptc_steps.append(upsert_text_step(tag_name, values))
        except ValueError:
            return None
    if has_iptc_digest_mode_step and not iptc_steps:
        return None
    if not steps and not iptc_steps:
        return None
    iptc_plan = (
        IptcApplicationWritePlan(coalesce_iptc_application_steps(tuple(iptc_steps)))
        if iptc_steps
        else None
    )
    return PhotoshopApp13ResourceWritePlan(tuple(steps), iptc_plan=iptc_plan)


def photoshop_app13_resource_write_step(
    tag: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    group, tag_name = public_write_tag_parts(tag)
    if group != "photoshop":
        return None
    normalized_name = tag_name.casefold().replace("_", "")
    if normalized_name == "copyrightflag":
        flag = parse_boolean_resource_value(value)
        if flag is None:
            return None
        return PhotoshopApp13ResourceWriteStep(
            tag_name="CopyrightFlag",
            resource_id=PHOTOSHOP_RESOURCE_ID_COPYRIGHT_FLAG,
            data=bytes((flag,)),
        )
    if normalized_name == "url":
        try:
            encoded = value.encode("latin-1")
        except UnicodeEncodeError:
            return None
        return PhotoshopApp13ResourceWriteStep(
            tag_name="URL",
            resource_id=PHOTOSHOP_RESOURCE_ID_URL,
            data=encoded,
        )
    if normalized_name == "globalangle":
        return uint32_step("GlobalAngle", PHOTOSHOP_RESOURCE_ID_GLOBAL_ANGLE, value)
    if normalized_name == "globalaltitude":
        return uint32_step("GlobalAltitude", PHOTOSHOP_RESOURCE_ID_GLOBAL_ALTITUDE, value)
    if normalized_name == "iptcdigest" and _HEXADECIMAL_DIGEST_RE.match(value):
        return PhotoshopApp13ResourceWriteStep(
            tag_name="IPTCDigest",
            resource_id=PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
            data=bytes.fromhex(value),
        )
    if normalized_name == "iptcdigest" and value.casefold() in {"new", "old"}:
        return PhotoshopApp13ResourceWriteStep(
            tag_name="IPTCDigest",
            resource_id=PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
            patch=PhotoshopApp13ResourcePatch(
                kind="iptc_digest",
                field_name="IPTCDigest",
                value=value.casefold(),
            ),
        )
    resolution_step = resolution_info_step(tag_name, normalized_name, value)
    if resolution_step is not None:
        return resolution_step
    quality_step = jpeg_quality_step(tag_name, normalized_name, value)
    if quality_step is not None:
        return quality_step
    print_scale_step = print_scale_info_step(tag_name, normalized_name, value)
    if print_scale_step is not None:
        return print_scale_step
    version_step = version_info_step(tag_name, normalized_name, value)
    if version_step is not None:
        return version_step
    pixel_step = pixel_info_step(tag_name, normalized_name, value)
    if pixel_step is not None:
        return pixel_step
    return None


def photoshop_app13_assignment_blocker_reason(
    tag: str,
) -> PhotoshopApp13AssignmentBlockerReason:
    """Classify residual public Photoshop APP13 assignment blockers.

    This is intentionally diagnostic-only.  URL_List is exposed in list-writable
    diagnostics, but writes warn that the tag has no inverse conversion, and
    thumbnail resources are binary payloads outside the public safe set.
    """

    group, tag_name = public_write_tag_parts(tag)
    if group != "photoshop":
        return "not_photoshop_app13_assignment"
    normalized_name = tag_name.casefold().replace("_", "")
    if normalized_name == "urllist":
        return "url_list_no_valueconvinv"
    if normalized_name in {"photoshopthumbnail", "photoshopbgrthumbnail"}:
        return "thumbnail_binary_payload"
    return "unsupported_photoshop_app13_tag"


def rewrite_photoshop_app13_resource_section(
    resource_section: bytes,
    plan: PhotoshopApp13ResourceWritePlan,
) -> bytes:
    """Apply simple IRB replacements/insertions using WritePhotoshop ordering rules."""

    blocks = parse_image_resource_blocks(resource_section)
    resource_data = {block.resource_id: block.data for block in blocks}
    existing_resource_ids = {block.resource_id for block in blocks}
    replacement_data = projected_resource_replacements(plan, resource_data)
    mutations = tuple(
        PhotoshopImageResourceMutation(
            action="replace" if resource_id in existing_resource_ids else "insert",
            resource_id=resource_id,
            data=data,
        )
        for resource_id, data in replacement_data
    )
    return apply_image_resource_entry_mutations(
        resource_section,
        mutations,
        source_backed=True,
        synthetic_resource_section=True,
    )


def create_photoshop_app13_resource_section(
    plan: PhotoshopApp13ResourceWritePlan,
) -> bytes:
    replacement_data = projected_resource_replacements(plan, {})
    entries = tuple(
        PhotoshopImageResourceEntry(
            signature=PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
            resource_id=resource_id,
            name=b"",
            data=data,
        )
        for resource_id, data in sorted(replacement_data)
    )
    return encode_image_resource_section(entries)


def public_write_tag_parts(tag: str) -> tuple[str, str]:
    if ":" not in tag:
        return "", tag
    group, tag_name = tag.split(":", 1)
    return group.casefold(), tag_name


def uint32_step(
    tag_name: str,
    resource_id: int,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    try:
        parsed_value = int(value, 10)
    except ValueError:
        return None
    if parsed_value < 0 or parsed_value > UINT32_MAX:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=resource_id,
        data=parsed_value.to_bytes(4, "big"),
    )


def resolution_info_step(
    tag_name: str,
    normalized_name: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    if normalized_name not in {
        "xresolution",
        "displayedunitsx",
        "yresolution",
        "displayedunitsy",
    }:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO,
        patch=PhotoshopApp13ResourcePatch("resolution", normalized_name, value),
    )


def jpeg_quality_step(
    tag_name: str,
    normalized_name: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    if normalized_name not in {"photoshopquality", "photoshopformat", "progressivescans"}:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=PHOTOSHOP_RESOURCE_ID_JPEG_QUALITY,
        patch=PhotoshopApp13ResourcePatch("jpeg_quality", normalized_name, value),
    )


def print_scale_info_step(
    tag_name: str,
    normalized_name: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    if normalized_name not in {"printstyle", "printposition", "printscale"}:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=PHOTOSHOP_RESOURCE_ID_PRINT_SCALE_INFO,
        patch=PhotoshopApp13ResourcePatch("print_scale", normalized_name, value),
    )


def version_info_step(
    tag_name: str,
    normalized_name: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    if normalized_name != "hasrealmergeddata":
        return None
    if parse_boolean_resource_value(value) is None:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=PHOTOSHOP_RESOURCE_ID_VERSION_INFO,
        patch=PhotoshopApp13ResourcePatch("version_info", normalized_name, value),
    )


def pixel_info_step(
    tag_name: str,
    normalized_name: str,
    value: str,
) -> PhotoshopApp13ResourceWriteStep | None:
    if normalized_name != "pixelaspectratio":
        return None
    try:
        float(value)
    except ValueError:
        return None
    return PhotoshopApp13ResourceWriteStep(
        tag_name=tag_name,
        resource_id=PHOTOSHOP_RESOURCE_ID_PIXEL_INFO,
        patch=PhotoshopApp13ResourcePatch("pixel_info", normalized_name, value),
    )


def projected_resource_replacements(
    plan: PhotoshopApp13ResourceWritePlan,
    resource_data: dict[int, bytes],
) -> tuple[tuple[int, bytes], ...]:
    replacements: dict[int, bytes] = {}
    source_iptc = resource_data.get(PHOTOSHOP_RESOURCE_ID_IPTC_DATA, b"")
    rewritten_iptc = source_iptc
    if plan.iptc_plan is not None:
        rewritten_iptc = apply_iptc_application_write_plan(source_iptc, plan.iptc_plan)
        if rewritten_iptc:
            replacements[PHOTOSHOP_RESOURCE_ID_IPTC_DATA] = rewritten_iptc

    for step in plan.steps:
        if step.data is not None:
            replacements[step.resource_id] = step.data
            continue
        if step.patch is None:
            continue
        if step.patch.kind == "iptc_digest":
            replacements[step.resource_id] = projected_iptc_digest(
                step.patch.value,
                source_iptc=source_iptc,
                rewritten_iptc=rewritten_iptc,
            )
            continue
        current = replacements.get(step.resource_id, resource_data.get(step.resource_id))
        if current is None:
            current = default_photoshop_app13_resource_payload(step.patch)
        replacements[step.resource_id] = apply_resource_patch(current, step.patch)
    return tuple(replacements.items())


def default_photoshop_app13_resource_payload(patch: PhotoshopApp13ResourcePatch) -> bytes:
    """Return the fixed binary table seed used for synthetic APP13 resource creation."""

    if patch.kind == "resolution":
        return b"\x00" * 16
    if patch.kind == "jpeg_quality":
        return b"\x00" * 6
    if patch.kind == "print_scale":
        return b"\x00" * 14
    if patch.kind == "version_info":
        return b"\x00" * 5
    if patch.kind == "pixel_info":
        return b"\x00" * 12
    raise ValueError(f"Unsupported Photoshop APP13 resource creation patch: {patch.kind}")


def projected_iptc_digest(
    mode: str,
    *,
    source_iptc: bytes,
    rewritten_iptc: bytes,
) -> bytes:
    if mode == "new":
        if not rewritten_iptc:
            raise ValueError("Photoshop:IPTCDigest=new requires IPTC data to digest.")
        from hashlib import md5

        return md5(rewritten_iptc, usedforsecurity=False).digest()
    if mode == "old":
        if not source_iptc:
            raise ValueError("Photoshop:IPTCDigest=old requires source IPTC data to digest.")
        from hashlib import md5

        return md5(source_iptc, usedforsecurity=False).digest()
    raise ValueError(f"Unsupported IPTCDigest mode: {mode}")


def apply_resource_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if patch.kind == "resolution":
        return apply_resolution_patch(data, patch)
    if patch.kind == "jpeg_quality":
        return apply_jpeg_quality_patch(data, patch)
    if patch.kind == "print_scale":
        return apply_print_scale_patch(data, patch)
    if patch.kind == "version_info":
        return apply_version_info_patch(data, patch)
    if patch.kind == "pixel_info":
        return apply_pixel_info_patch(data, patch)
    raise ValueError(f"Unsupported Photoshop APP13 resource patch: {patch.kind}")


def apply_resolution_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if len(data) < 16:
        raise ValueError("Photoshop ResolutionInfo source resource is too short.")
    rewritten = bytearray(data)
    if patch.field_name in {"xresolution", "yresolution"}:
        value = parse_fixed_16_16(patch.value)
        offset = 0 if patch.field_name == "xresolution" else 8
        rewritten[offset : offset + 4] = value.to_bytes(4, "big")
        return bytes(rewritten)
    unit = parse_resolution_unit(patch.value)
    offset = 4 if patch.field_name == "displayedunitsx" else 12
    rewritten[offset : offset + 2] = unit.to_bytes(2, "big")
    return bytes(rewritten)


def apply_jpeg_quality_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if len(data) < 6:
        raise ValueError("Photoshop JPEG_Quality source resource is too short.")
    rewritten = bytearray(data)
    if patch.field_name == "photoshopquality":
        quality = parse_int_range(patch.value, -32764, 32771) - 4
        rewritten[0:2] = quality.to_bytes(2, "big", signed=True)
    elif patch.field_name == "photoshopformat":
        rewritten[2:4] = parse_photoshop_format(patch.value).to_bytes(2, "big")
    else:
        rewritten[4:6] = parse_progressive_scans(patch.value).to_bytes(2, "big")
    return bytes(rewritten)


def apply_print_scale_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if len(data) < 14:
        raise ValueError("Photoshop PrintScaleInfo source resource is too short.")
    rewritten = bytearray(data)
    if patch.field_name == "printstyle":
        rewritten[0:2] = parse_print_style(patch.value).to_bytes(2, "big")
    elif patch.field_name == "printposition":
        x_position, y_position = parse_float_pair(patch.value)
        rewritten[2:6] = struct.pack(">f", x_position)
        rewritten[6:10] = struct.pack(">f", y_position)
    else:
        rewritten[10:14] = struct.pack(">f", float(patch.value))
    return bytes(rewritten)


def apply_version_info_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if len(data) < 5:
        raise ValueError("Photoshop VersionInfo source resource is too short.")
    merged_data = parse_boolean_resource_value(patch.value)
    if merged_data is None:
        raise ValueError("HasRealMergedData requires a boolean value.")
    rewritten = bytearray(data)
    rewritten[4] = merged_data
    return bytes(rewritten)


def apply_pixel_info_patch(data: bytes, patch: PhotoshopApp13ResourcePatch) -> bytes:
    if len(data) < 12:
        raise ValueError("Photoshop PixelInfo source resource is too short.")
    rewritten = bytearray(data)
    rewritten[4:12] = struct.pack(">d", float(patch.value))
    return bytes(rewritten)


def parse_fixed_16_16(value: str) -> int:
    parsed = float(value)
    fixed = int(parsed * 65536 + 0.5)
    if fixed < 0 or fixed > UINT32_MAX:
        raise ValueError("Resolution must fit in unsigned 16.16 fixed point.")
    return fixed


def parse_resolution_unit(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized == "inches":
        return 1
    if normalized == "cm":
        return 2
    return parse_int_range(value, 0, 0xFFFF)


def parse_photoshop_format(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 0x0000
    if normalized == "optimized":
        return 0x0001
    if normalized == "progressive":
        return 0x0101
    return parse_int_range(value, 0, 0xFFFF)


def parse_progressive_scans(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized.endswith("scans"):
        normalized = normalized.removesuffix("scans").strip()
    if normalized in {"3", "4", "5"} and "scans" in value.casefold():
        return int(normalized, 10) - 2
    return parse_int_range(normalized, 0, 0xFFFF)


def parse_print_style(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized == "centered":
        return 0
    if normalized == "size to fit":
        return 1
    if normalized == "user defined":
        return 2
    return parse_int_range(value, 0, 0xFFFF)


def parse_float_pair(value: str) -> tuple[float, float]:
    parts = value.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("PrintPosition requires two numeric values.")
    return float(parts[0]), float(parts[1])


def parse_int_range(value: str, minimum: int, maximum: int) -> int:
    parsed = int(value, 10)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"Integer value must be in range {minimum}..{maximum}.")
    return parsed


def parse_boolean_resource_value(value: str) -> int | None:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return 1
    if normalized in {"0", "false", "no"}:
        return 0
    return None
