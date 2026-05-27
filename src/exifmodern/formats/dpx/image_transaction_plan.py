"""Source-grounded, preserve-first DPX image transaction plans.

ExifTool's DPX module validates a fixed 2080-byte header window, selects byte
order from the signature, warns when the generic plus industry header length is
not 2048 bytes, and extracts fixed-offset metadata from that window.  It does
not declare a DPX write path, so this planner preserves bytes and blocks
requested rewrites.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Literal

DPX_EXIFTOOL_READ_SIZE = 2080
DPX_EXPECTED_HEADER_LENGTH = 2048
DPX_PM_SOURCE_PATH = "lib/Image/ExifTool/DPX.pm"

type DpxPlanStatus = Literal["planned", "unsupported"]
type DpxEndian = Literal["big", "little"]
type DpxByteOrderName = Literal["Big-endian", "Little-endian"]
type DpxRewriteOperation = Literal["insert", "replace", "delete"]
type DpxReadValue = str | int | float
type DpxRewriteTarget = Literal[
    "file_header",
    "image_information",
    "image_source_metadata",
    "film_metadata",
    "television_metadata",
    "user_metadata",
    "image_payload",
]
type DpxActionKind = Literal[
    "validate_signature_header",
    "select_byte_order",
    "extract_file_header_metadata",
    "check_declared_header_length",
    "extract_image_geometry",
    "extract_image_element_layout",
    "extract_image_descriptions",
    "extract_image_source_metadata",
    "extract_film_metadata",
    "extract_television_metadata",
    "extract_user_metadata",
    "preserve_oracle_header_window",
    "preserve_image_payload",
    "block_requested_rewrite",
]
type DpxEmissionGateCode = Literal[
    "truncated_dpx_header",
    "unsupported_dpx_signature",
    "unexpected_dpx_header_length",
    "rewrite_requested_requires_dpx_writer",
    "non_mutating_plan_requires_explicit_emission",
]

DPX_DESCRIPTION_SOURCE = "dpx.description"
DPX_MAIN_TABLE_SOURCE = "dpx.main.table"
DPX_FILE_HEADER_SOURCE = "dpx.file.header"
DPX_IMAGE_INFO_SOURCE = "dpx.image.info"
DPX_IMAGE_SOURCE_SOURCE = "dpx.image.source"
DPX_FILM_SOURCE = "dpx.film"
DPX_TELEVISION_SOURCE = "dpx.television"
DPX_USER_SOURCE = "dpx.user"
DPX_PROCESS_GATE_SOURCE = "dpx.process.gate"
DPX_PROCESS_DIRECTORY_SOURCE = "dpx.process.directory"
DPX_COMPOSITE_SOURCE = "dpx.composite"
DPX_READ_ONLY_SOURCE = "dpx.read.only"

DPX_TRANSACTION_SOURCES = (
    DPX_DESCRIPTION_SOURCE,
    DPX_MAIN_TABLE_SOURCE,
    DPX_FILE_HEADER_SOURCE,
    DPX_IMAGE_INFO_SOURCE,
    DPX_IMAGE_SOURCE_SOURCE,
    DPX_FILM_SOURCE,
    DPX_TELEVISION_SOURCE,
    DPX_USER_SOURCE,
    DPX_PROCESS_GATE_SOURCE,
    DPX_PROCESS_DIRECTORY_SOURCE,
    DPX_READ_ONLY_SOURCE,
)

ORIENTATION_DESCRIPTIONS: dict[int, str] = {
    0: "Horizontal (normal)",
    1: "Mirror vertical",
    2: "Mirror horizontal",
    3: "Rotate 180",
    4: "Mirror horizontal and rotate 270 CW",
    5: "Rotate 90 CW",
    6: "Rotate 270 CW",
    7: "Mirror horizontal and rotate 90 CW",
}
DITTO_KEY_DESCRIPTIONS: dict[int, str] = {0: "Same", 1: "New"}
DATA_SIGN_DESCRIPTIONS: dict[int, str] = {0: "Unsigned", 1: "Signed"}
COMPONENTS_CONFIGURATION_DESCRIPTIONS: dict[int, str] = {
    0: "User-defined single component",
    1: "Red (R)",
    2: "Green (G)",
    3: "Blue (B)",
    4: "Alpha (matte)",
    6: "Luminance (Y)",
    7: "Chrominance (Cb, Cr, subsampled by two)",
    8: "Depth (Z)",
    9: "Composite video",
    50: "R, G, B",
    51: "R, G, B, Alpha",
    52: "Alpha, B, G, R",
    100: "Cb, Y, Cr, Y (4:2:2)",
    101: "Cb, Y, A, Cr, Y, A (4:2:2:4)",
    102: "Cb, Y, Cr (4:4:4)",
    103: "Cb, Y, Cr, A (4:4:4:4)",
    150: "User-defined 2 component element",
    151: "User-defined 3 component element",
    152: "User-defined 4 component element",
    153: "User-defined 5 component element",
    154: "User-defined 6 component element",
    155: "User-defined 7 component element",
    156: "User-defined 8 component element",
}
TRANSFER_CHARACTERISTIC_DESCRIPTIONS: dict[int, str] = {
    0: "User-defined",
    1: "Printing density",
    2: "Linear",
    3: "Logarithmic",
    4: "Unspecified video",
    5: "SMPTE 274M",
    6: "ITU-R 709-4",
    7: "ITU-R 601-5 system B or G (625)",
    8: "ITU-R 601-5 system M (525)",
    9: "Composite video (NTSC)",
    10: "Composite video (PAL)",
    11: "Z (depth) - linear",
    12: "Z (depth) - homogeneous",
    13: "SMPTE ADX",
    14: "ITU-R 2020 NCL",
    15: "ITU-R 2020 CL",
    16: "IEC 61966-2-4 xvYCC",
    17: "ITU-R 2100 NCL/PQ",
    18: "ITU-R 2100 ICtCp/PQ",
    19: "ITU-R 2100 NCL/HLG",
    20: "ITU-R 2100 ICtCp/HLG",
    21: "RP 431-2:2011 Gama 2.6",
    22: "IEC 61966-2-1 sRGB",
}
COLORIMETRIC_SPECIFICATION_DESCRIPTIONS: dict[int, str] = {
    0: "User-defined",
    1: "Printing density",
    4: "Unspecified video",
    5: "SMPTE 274M",
    6: "ITU-R 709-4",
    7: "ITU-R 601-5 system B or G (625)",
    8: "ITU-R 601-5 system M (525)",
    9: "Composite video (NTSC)",
    10: "Composite video (PAL)",
    13: "SMPTE ADX",
    14: "ITU-R 2020",
    15: "P3D65",
    16: "P3DCI",
    17: "P3D60",
    18: "ACES",
}


@dataclass(frozen=True)
class DpxRewriteRequest:
    target: DpxRewriteTarget
    operation: DpxRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class DpxOutputEmissionGate:
    code: DpxEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxHeaderValidationPlan:
    signature: bytes
    header_bytes_read: int
    endian: DpxEndian | None
    byte_order_name: DpxByteOrderName | None
    header_version: str | None
    generic_header_size: int | None
    industry_header_size: int | None
    declared_header_length: int | None
    reason: DpxEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason not in {"truncated_dpx_header", "unsupported_dpx_signature"}


@dataclass(frozen=True)
class DpxFileHeaderPlan:
    dpx_file_size: int | None
    ditto_key: int | None
    ditto_key_description: str | None
    image_file_name: str | None
    create_date: str | None
    creator: str | None
    project: str | None
    copyright: str | None
    encryption_key_hex: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxImageInformationPlan:
    orientation: int | None
    orientation_description: str | None
    image_elements: int | None
    image_width: int | None
    image_height: int | None
    data_sign: int | None
    data_sign_description: str | None
    components_configuration: int | None
    components_configuration_description: str | None
    transfer_characteristic: int | None
    transfer_characteristic_description: str | None
    colorimetric_specification: int | None
    colorimetric_specification_description: str | None
    bit_depth: int | None
    image_descriptions: tuple[str, ...]
    packing_supported_by_oracle: bool
    encoding_supported_by_oracle: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxImageSourceMetadataPlan:
    source_file_name: str | None
    source_create_date: str | None
    input_device_name: str | None
    input_device_serial_number: str | None
    aspect_ratio: tuple[int, int] | None
    aspect_ratio_description: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxFilmMetadataPlan:
    original_frame_rate: float | None
    shutter_angle: float | None
    frame_id: str | None
    slate_information: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxTelevisionMetadataPlan:
    time_code: int | None
    frame_rate: float | None
    reserved5_range: tuple[int, int] | None
    reserved5_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxUserMetadataPlan:
    user_id: str | None
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxPayloadPlan:
    oracle_header_range: tuple[int, int] | None
    payload_range: tuple[int, int] | None
    action: Literal["preserve"]
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int | None:
        if self.payload_range is None:
            return None
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class DpxReadTagRecord:
    name: str
    group: str
    tag_id: str
    raw_value: DpxReadValue
    rendered_value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxActionPlan:
    kind: DpxActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DpxImageTransactionPlan:
    status: DpxPlanStatus
    source_data: bytes
    header_validation: DpxHeaderValidationPlan
    file_header: DpxFileHeaderPlan
    image_information: DpxImageInformationPlan
    image_source_metadata: DpxImageSourceMetadataPlan
    film_metadata: DpxFilmMetadataPlan
    television_metadata: DpxTelevisionMetadataPlan
    user_metadata: DpxUserMetadataPlan
    read_tags: tuple[DpxReadTagRecord, ...]
    payload: DpxPayloadPlan
    actions: tuple[DpxActionPlan, ...]
    output_emission_gates: tuple[DpxOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"DPX image transaction output is gated: {gate_codes}")
        return self.source_data


def build_dpx_image_transaction_plan(
    dpx_data: bytes,
    *,
    rewrite_requests: tuple[DpxRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> DpxImageTransactionPlan:
    """Build a preserve-only DPX image transaction plan from in-memory bytes."""

    gates: list[DpxOutputEmissionGate] = []
    header_validation = build_dpx_header_validation_plan(dpx_data)
    if header_validation.reason is not None:
        gates.append(
            DpxOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's DPX header gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    file_header = build_dpx_file_header_plan(dpx_data, header_validation)
    image_information = build_dpx_image_information_plan(dpx_data, header_validation)
    image_source_metadata = build_dpx_image_source_metadata_plan(dpx_data, header_validation)
    film_metadata = build_dpx_film_metadata_plan(dpx_data, header_validation)
    television_metadata = build_dpx_television_metadata_plan(dpx_data, header_validation)
    user_metadata = build_dpx_user_metadata_plan(dpx_data, header_validation)
    payload = build_dpx_payload_plan(dpx_data, header_validation)
    read_tags = build_dpx_read_tags(
        header_validation,
        file_header,
        image_information,
        image_source_metadata,
        film_metadata,
        television_metadata,
        user_metadata,
    )
    actions = build_dpx_actions(
        header_validation,
        file_header,
        image_information,
        image_source_metadata,
        film_metadata,
        television_metadata,
        user_metadata,
        payload,
        rewrite_requests,
    )
    if rewrite_requests:
        gates.append(
            DpxOutputEmissionGate(
                code="rewrite_requested_requires_dpx_writer",
                reason="DPX.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(DPX_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: DpxPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    evidence_ids = unique_evidence_ids(
        (
            *DPX_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *file_header.evidence_ids,
            *image_information.evidence_ids,
            *image_source_metadata.evidence_ids,
            *film_metadata.evidence_ids,
            *television_metadata.evidence_ids,
            *user_metadata.evidence_ids,
            *payload.evidence_ids,
            *(evidence_id for action in actions for evidence_id in action.evidence_ids),
            *(evidence_id for gate in unique_gates for evidence_id in gate.evidence_ids),
        )
    )
    return DpxImageTransactionPlan(
        status=status,
        source_data=dpx_data,
        header_validation=header_validation,
        file_header=file_header,
        image_information=image_information,
        image_source_metadata=image_source_metadata,
        film_metadata=film_metadata,
        television_metadata=television_metadata,
        user_metadata=user_metadata,
        read_tags=read_tags,
        payload=payload,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=evidence_ids,
    )


def build_dpx_header_validation_plan(dpx_data: bytes) -> DpxHeaderValidationPlan:
    header_bytes_read = min(len(dpx_data), DPX_EXIFTOOL_READ_SIZE)
    signature = dpx_data[:4]
    if len(dpx_data) < DPX_EXIFTOOL_READ_SIZE:
        return DpxHeaderValidationPlan(
            signature=signature,
            header_bytes_read=header_bytes_read,
            endian=None,
            byte_order_name=None,
            header_version=None,
            generic_header_size=None,
            industry_header_size=None,
            declared_header_length=None,
            reason="truncated_dpx_header",
            evidence_ids=(DPX_PROCESS_GATE_SOURCE,),
        )
    if signature not in {b"SDPX", b"XPDS"}:
        return DpxHeaderValidationPlan(
            signature=signature,
            header_bytes_read=header_bytes_read,
            endian=None,
            byte_order_name=None,
            header_version=None,
            generic_header_size=None,
            industry_header_size=None,
            declared_header_length=None,
            reason="unsupported_dpx_signature",
            evidence_ids=(DPX_PROCESS_GATE_SOURCE,),
        )

    endian: DpxEndian = "big" if signature == b"SDPX" else "little"
    byte_order_name: DpxByteOrderName = "Big-endian" if endian == "big" else "Little-endian"
    generic_header_size = read_u32(dpx_data, 24, endian)
    industry_header_size = read_u32(dpx_data, 28, endian)
    declared_header_length = generic_header_size + industry_header_size
    reason: DpxEmissionGateCode | None = (
        "unexpected_dpx_header_length"
        if declared_header_length != DPX_EXPECTED_HEADER_LENGTH
        else None
    )
    return DpxHeaderValidationPlan(
        signature=signature,
        header_bytes_read=header_bytes_read,
        endian=endian,
        byte_order_name=byte_order_name,
        header_version=read_string(dpx_data, 8, 8),
        generic_header_size=generic_header_size,
        industry_header_size=industry_header_size,
        declared_header_length=declared_header_length,
        reason=reason,
        evidence_ids=(DPX_PROCESS_GATE_SOURCE, DPX_FILE_HEADER_SOURCE),
    )


def build_dpx_file_header_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxFileHeaderPlan:
    if not validation.is_exiftool_accepted or validation.endian is None:
        return DpxFileHeaderPlan(
            dpx_file_size=None,
            ditto_key=None,
            ditto_key_description=None,
            image_file_name=None,
            create_date=None,
            creator=None,
            project=None,
            copyright=None,
            encryption_key_hex=None,
            evidence_ids=(DPX_FILE_HEADER_SOURCE,),
        )
    ditto_key = read_u32(dpx_data, 20, validation.endian)
    encryption_key = read_u32(dpx_data, 660, validation.endian)
    return DpxFileHeaderPlan(
        dpx_file_size=read_u32(dpx_data, 16, validation.endian),
        ditto_key=ditto_key,
        ditto_key_description=DITTO_KEY_DESCRIPTIONS.get(ditto_key),
        image_file_name=read_string(dpx_data, 36, 100),
        create_date=normalize_dpx_datetime(read_string(dpx_data, 136, 24)),
        creator=read_string(dpx_data, 160, 100),
        project=read_string(dpx_data, 260, 200),
        copyright=read_string(dpx_data, 460, 200),
        encryption_key_hex=f"{encryption_key:08x}",
        evidence_ids=(DPX_FILE_HEADER_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_image_information_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxImageInformationPlan:
    if not validation.is_exiftool_accepted or validation.endian is None:
        return DpxImageInformationPlan(
            orientation=None,
            orientation_description=None,
            image_elements=None,
            image_width=None,
            image_height=None,
            data_sign=None,
            data_sign_description=None,
            components_configuration=None,
            components_configuration_description=None,
            transfer_characteristic=None,
            transfer_characteristic_description=None,
            colorimetric_specification=None,
            colorimetric_specification_description=None,
            bit_depth=None,
            image_descriptions=(),
            packing_supported_by_oracle=False,
            encoding_supported_by_oracle=False,
            evidence_ids=(DPX_IMAGE_INFO_SOURCE,),
        )
    orientation = read_u16(dpx_data, 768, validation.endian)
    data_sign = read_u32(dpx_data, 780, validation.endian)
    components_configuration = dpx_data[800]
    transfer_characteristic = dpx_data[801]
    colorimetric_specification = dpx_data[802]
    descriptions = tuple(
        description
        for description in (
            read_image_description(dpx_data, 820),
            read_image_description(dpx_data, 892),
            read_image_description(dpx_data, 964),
            read_image_description(dpx_data, 1036),
            read_image_description(dpx_data, 1108),
            read_image_description(dpx_data, 1180),
            read_image_description(dpx_data, 1252),
            read_image_description(dpx_data, 1324),
        )
        if description is not None
    )
    return DpxImageInformationPlan(
        orientation=orientation,
        orientation_description=ORIENTATION_DESCRIPTIONS.get(orientation),
        image_elements=read_u16(dpx_data, 770, validation.endian),
        image_width=read_u32(dpx_data, 772, validation.endian),
        image_height=read_u32(dpx_data, 776, validation.endian),
        data_sign=data_sign,
        data_sign_description=DATA_SIGN_DESCRIPTIONS.get(data_sign),
        components_configuration=components_configuration,
        components_configuration_description=COMPONENTS_CONFIGURATION_DESCRIPTIONS.get(
            components_configuration
        ),
        transfer_characteristic=transfer_characteristic,
        transfer_characteristic_description=TRANSFER_CHARACTERISTIC_DESCRIPTIONS.get(
            transfer_characteristic
        ),
        colorimetric_specification=colorimetric_specification,
        colorimetric_specification_description=COLORIMETRIC_SPECIFICATION_DESCRIPTIONS.get(
            colorimetric_specification
        ),
        bit_depth=dpx_data[803],
        image_descriptions=descriptions,
        packing_supported_by_oracle=False,
        encoding_supported_by_oracle=False,
        evidence_ids=(DPX_IMAGE_INFO_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_image_source_metadata_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxImageSourceMetadataPlan:
    if not validation.is_exiftool_accepted or validation.endian is None:
        return DpxImageSourceMetadataPlan(
            source_file_name=None,
            source_create_date=None,
            input_device_name=None,
            input_device_serial_number=None,
            aspect_ratio=None,
            aspect_ratio_description=None,
            evidence_ids=(DPX_IMAGE_SOURCE_SOURCE,),
        )
    numerator = read_u32(dpx_data, 1628, validation.endian)
    denominator = read_u32(dpx_data, 1632, validation.endian)
    aspect_ratio = normalize_aspect_ratio(numerator, denominator)
    return DpxImageSourceMetadataPlan(
        source_file_name=read_string(dpx_data, 1432, 100),
        source_create_date=read_string(dpx_data, 1532, 24),
        input_device_name=read_string(dpx_data, 1556, 32),
        input_device_serial_number=read_string(dpx_data, 1588, 32),
        aspect_ratio=aspect_ratio,
        aspect_ratio_description=describe_aspect_ratio(aspect_ratio),
        evidence_ids=(DPX_IMAGE_SOURCE_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_film_metadata_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxFilmMetadataPlan:
    if not validation.is_exiftool_accepted or validation.endian is None:
        return DpxFilmMetadataPlan(
            original_frame_rate=None,
            shutter_angle=None,
            frame_id=None,
            slate_information=None,
            evidence_ids=(DPX_FILM_SOURCE,),
        )
    return DpxFilmMetadataPlan(
        original_frame_rate=read_float32_if_meaningful(dpx_data, 1724, validation.endian),
        shutter_angle=read_float32_if_meaningful(dpx_data, 1728, validation.endian),
        frame_id=read_string(dpx_data, 1732, 32),
        slate_information=read_string(dpx_data, 1764, 100),
        evidence_ids=(DPX_FILM_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_television_metadata_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxTelevisionMetadataPlan:
    if not validation.is_exiftool_accepted or validation.endian is None:
        return DpxTelevisionMetadataPlan(
            time_code=None,
            frame_rate=None,
            reserved5_range=None,
            reserved5_preserved=False,
            evidence_ids=(DPX_TELEVISION_SOURCE,),
        )
    return DpxTelevisionMetadataPlan(
        time_code=read_u32(dpx_data, 1920, validation.endian),
        frame_rate=read_float32_if_meaningful(dpx_data, 1940, validation.endian),
        reserved5_range=(1972, 2048),
        reserved5_preserved=True,
        evidence_ids=(DPX_TELEVISION_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_user_metadata_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxUserMetadataPlan:
    if not validation.is_exiftool_accepted:
        return DpxUserMetadataPlan(
            user_id=None,
            byte_range=None,
            evidence_ids=(DPX_USER_SOURCE,),
        )
    return DpxUserMetadataPlan(
        user_id=read_string(dpx_data, 2048, 32),
        byte_range=(2048, 2080),
        evidence_ids=(DPX_USER_SOURCE, DPX_PROCESS_DIRECTORY_SOURCE),
    )


def build_dpx_payload_plan(
    dpx_data: bytes,
    validation: DpxHeaderValidationPlan,
) -> DpxPayloadPlan:
    if not validation.is_exiftool_accepted:
        return DpxPayloadPlan(
            oracle_header_range=None,
            payload_range=None,
            action="preserve",
            evidence_ids=(DPX_READ_ONLY_SOURCE,),
        )
    return DpxPayloadPlan(
        oracle_header_range=(0, DPX_EXIFTOOL_READ_SIZE),
        payload_range=(DPX_EXIFTOOL_READ_SIZE, len(dpx_data)),
        action="preserve",
        evidence_ids=(DPX_PROCESS_DIRECTORY_SOURCE, DPX_READ_ONLY_SOURCE),
    )


def build_dpx_read_tags(
    validation: DpxHeaderValidationPlan,
    file_header: DpxFileHeaderPlan,
    image_information: DpxImageInformationPlan,
    image_source_metadata: DpxImageSourceMetadataPlan,
    film_metadata: DpxFilmMetadataPlan,
    television_metadata: DpxTelevisionMetadataPlan,
    user_metadata: DpxUserMetadataPlan,
) -> tuple[DpxReadTagRecord, ...]:
    if not validation.is_exiftool_accepted:
        return ()
    tags: list[DpxReadTagRecord] = []
    _append_dpx_tag(
        tags,
        "ByteOrder",
        "File",
        validation.signature.decode("ascii"),
        validation.byte_order_name,
        DPX_FILE_HEADER_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "HeaderVersion",
        "File",
        validation.header_version,
        validation.header_version,
        DPX_FILE_HEADER_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "DPXFileSize",
        "File",
        file_header.dpx_file_size,
        file_header.dpx_file_size,
        DPX_FILE_HEADER_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "DittoKey",
        "File",
        file_header.ditto_key,
        file_header.ditto_key_description,
        DPX_FILE_HEADER_SOURCE,
    )
    for name, group, value in (
        ("ImageFileName", "Image", file_header.image_file_name),
        ("CreateDate", "Time", file_header.create_date),
        ("Creator", "Author", file_header.creator),
        ("Project", "Image", file_header.project),
        ("Copyright", "Author", file_header.copyright),
        ("EncryptionKey", "Image", file_header.encryption_key_hex),
    ):
        _append_dpx_tag(tags, name, group, value, value, DPX_FILE_HEADER_SOURCE)
    _append_dpx_tag(
        tags,
        "Orientation",
        "Image",
        image_information.orientation,
        image_information.orientation_description,
        DPX_IMAGE_INFO_SOURCE,
    )
    for name, image_value in (
        ("ImageElements", image_information.image_elements),
        ("ImageWidth", image_information.image_width),
        ("ImageHeight", image_information.image_height),
    ):
        _append_dpx_tag(
            tags,
            name,
            "Image",
            image_value,
            image_value,
            DPX_IMAGE_INFO_SOURCE,
        )
    _append_dpx_tag(
        tags,
        "DataSign",
        "Image",
        image_information.data_sign,
        image_information.data_sign_description,
        DPX_IMAGE_INFO_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "ComponentsConfiguration",
        "Image",
        image_information.components_configuration,
        image_information.components_configuration_description,
        DPX_IMAGE_INFO_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "TransferCharacteristic",
        "Image",
        image_information.transfer_characteristic,
        image_information.transfer_characteristic_description,
        DPX_IMAGE_INFO_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "ColorimetricSpecification",
        "Image",
        image_information.colorimetric_specification,
        image_information.colorimetric_specification_description,
        DPX_IMAGE_INFO_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "BitDepth",
        "Image",
        image_information.bit_depth,
        image_information.bit_depth,
        DPX_IMAGE_INFO_SOURCE,
    )
    for index, description in enumerate(image_information.image_descriptions, start=1):
        name = "ImageDescription" if index == 1 else f"Image{index}Description"
        _append_dpx_tag(tags, name, "Image", description, description, DPX_IMAGE_INFO_SOURCE)
    for name, evidence_id_value in (
        ("SourceFileName", image_source_metadata.source_file_name),
        ("SourceCreateDate", image_source_metadata.source_create_date),
        ("InputDeviceName", image_source_metadata.input_device_name),
        ("InputDeviceSerialNumber", image_source_metadata.input_device_serial_number),
    ):
        _append_dpx_tag(
            tags,
            name,
            "Image",
            evidence_id_value,
            evidence_id_value,
            DPX_IMAGE_SOURCE_SOURCE,
        )
    if image_source_metadata.aspect_ratio is not None:
        _append_dpx_tag(
            tags,
            "AspectRatio",
            "Image",
            f"{image_source_metadata.aspect_ratio[0]} {image_source_metadata.aspect_ratio[1]}",
            image_source_metadata.aspect_ratio_description,
            DPX_IMAGE_SOURCE_SOURCE,
        )
    for name, film_value in (
        ("OriginalFrameRate", film_metadata.original_frame_rate),
        ("ShutterAngle", film_metadata.shutter_angle),
        ("FrameID", film_metadata.frame_id),
        ("SlateInformation", film_metadata.slate_information),
    ):
        _append_dpx_tag(tags, name, "Image", film_value, film_value, DPX_FILM_SOURCE)
    _append_dpx_tag(
        tags,
        "TimeCode",
        "Image",
        television_metadata.time_code,
        television_metadata.time_code,
        DPX_TELEVISION_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "FrameRate",
        "Image",
        television_metadata.frame_rate,
        television_metadata.frame_rate,
        DPX_TELEVISION_SOURCE,
    )
    _append_dpx_tag(
        tags,
        "UserID",
        "Image",
        user_metadata.user_id,
        user_metadata.user_id,
        DPX_USER_SOURCE,
    )
    if image_information.image_width is not None and image_information.image_height is not None:
        width = image_information.image_width
        height = image_information.image_height
        megapixels = width * height / 1_000_000
        _append_dpx_tag(
            tags,
            "ImageSize",
            "Composite",
            f"{width}x{height}",
            f"{width}x{height}",
            DPX_COMPOSITE_SOURCE,
            tag_id="Exif-ImageSize",
        )
        _append_dpx_tag(
            tags,
            "Megapixels",
            "Composite",
            megapixels,
            round_dpx_megapixels(megapixels),
            DPX_COMPOSITE_SOURCE,
            tag_id="Exif-Megapixels",
        )
    return tuple(tags)


def _append_dpx_tag(
    tags: list[DpxReadTagRecord],
    name: str,
    group: str,
    raw_value: DpxReadValue | None,
    rendered_value: str | int | float | None,
    evidence_id: str,
    tag_id: str | None = None,
) -> None:
    if raw_value is None or rendered_value is None:
        return
    tags.append(
        DpxReadTagRecord(
            name=name,
            group=group,
            tag_id=name if tag_id is None else tag_id,
            raw_value=raw_value,
            rendered_value=str(rendered_value),
            evidence_ids=(evidence_id, DPX_PROCESS_DIRECTORY_SOURCE),
        )
    )


def build_dpx_actions(
    validation: DpxHeaderValidationPlan,
    file_header: DpxFileHeaderPlan,
    image_information: DpxImageInformationPlan,
    image_source_metadata: DpxImageSourceMetadataPlan,
    film_metadata: DpxFilmMetadataPlan,
    television_metadata: DpxTelevisionMetadataPlan,
    user_metadata: DpxUserMetadataPlan,
    payload: DpxPayloadPlan,
    rewrite_requests: tuple[DpxRewriteRequest, ...],
) -> tuple[DpxActionPlan, ...]:
    actions: list[DpxActionPlan] = [
        DpxActionPlan(
            kind="validate_signature_header",
            target="dpx_header_window",
            byte_range=(0, validation.header_bytes_read),
            reason="Mirror ExifTool's fixed 2080-byte DPX read and signature gate.",
            evidence_ids=(DPX_PROCESS_GATE_SOURCE,),
        )
    ]
    if validation.is_exiftool_accepted:
        actions.extend(
            (
                DpxActionPlan(
                    kind="select_byte_order",
                    target=validation.byte_order_name or "unknown",
                    byte_range=(0, 4),
                    reason="Set byte order from the SDPX or XPDS signature.",
                    evidence_ids=(DPX_PROCESS_GATE_SOURCE, DPX_FILE_HEADER_SOURCE),
                ),
                DpxActionPlan(
                    kind="extract_file_header_metadata",
                    target="file_header",
                    byte_range=(0, 664),
                    reason="Extract fixed-offset file header metadata from the DPX table.",
                    evidence_ids=file_header.evidence_ids,
                ),
                DpxActionPlan(
                    kind="check_declared_header_length",
                    target="generic_plus_industry_header_size",
                    byte_range=(24, 32),
                    reason="Warn or gate when generic plus industry size differs from 2048.",
                    evidence_ids=(DPX_PROCESS_GATE_SOURCE,),
                ),
                DpxActionPlan(
                    kind="extract_image_geometry",
                    target="orientation_dimensions",
                    byte_range=(768, 780),
                    reason="Extract orientation, element count, width, and height.",
                    evidence_ids=image_information.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_image_element_layout",
                    target="data_sign_components_transfer_color_depth",
                    byte_range=(780, 804),
                    reason=(
                        "Extract source-backed element layout fields; packing and encoding "
                        "are not DPX.pm tags."
                    ),
                    evidence_ids=image_information.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_image_descriptions",
                    target="image_description_strings",
                    byte_range=(820, 1356),
                    reason="Extract up to eight source-backed image description strings.",
                    evidence_ids=image_information.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_image_source_metadata",
                    target="image_source_metadata",
                    byte_range=(1432, 1636),
                    reason="Extract only image source fields present in DPX.pm.",
                    evidence_ids=image_source_metadata.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_film_metadata",
                    target="film_metadata",
                    byte_range=(1724, 1864),
                    reason="Extract film fields present in DPX.pm.",
                    evidence_ids=film_metadata.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_television_metadata",
                    target="television_metadata",
                    byte_range=(1920, 2048),
                    reason="Extract television fields and preserve Reserved5 as unknown.",
                    evidence_ids=television_metadata.evidence_ids,
                ),
                DpxActionPlan(
                    kind="extract_user_metadata",
                    target="user_metadata",
                    byte_range=user_metadata.byte_range,
                    reason="Extract UserID from the final 32 bytes of the fixed read window.",
                    evidence_ids=user_metadata.evidence_ids,
                ),
                DpxActionPlan(
                    kind="preserve_oracle_header_window",
                    target="dpx_oracle_header_window",
                    byte_range=payload.oracle_header_range,
                    reason="Preserve the same fixed window that DPX.pm processes.",
                    evidence_ids=payload.evidence_ids,
                ),
                DpxActionPlan(
                    kind="preserve_image_payload",
                    target="image_payload_after_oracle_window",
                    byte_range=payload.payload_range,
                    reason="Preserve bytes beyond DPX.pm's 2080-byte extraction window.",
                    evidence_ids=payload.evidence_ids,
                ),
            )
        )
    actions.extend(
        DpxActionPlan(
            kind="block_requested_rewrite",
            target=f"{request.operation}:{request.target}",
            byte_range=None,
            reason="DPX.pm has no writer, so the planner does not mutate DPX bytes.",
            evidence_ids=(DPX_READ_ONLY_SOURCE,),
        )
        for request in rewrite_requests
    )
    return tuple(actions)


def read_u16(data: bytes, offset: int, endian: DpxEndian) -> int:
    return int.from_bytes(data[offset : offset + 2], endian)


def read_u32(data: bytes, offset: int, endian: DpxEndian) -> int:
    return int.from_bytes(data[offset : offset + 4], endian)


def round_dpx_megapixels(value: float) -> float:
    if value >= 1:
        return round(value, 1)
    if value >= 0.001:
        return round(value, 3)
    return round(value, 6)


def read_float32_if_meaningful(data: bytes, offset: int, endian: DpxEndian) -> float | None:
    format_code = ">f" if endian == "big" else "<f"
    value = float(struct.unpack(format_code, data[offset : offset + 4])[0])
    if not math.isfinite(value):
        return None
    return value


def read_string(data: bytes, offset: int, length: int) -> str | None:
    raw = data[offset : offset + length]
    trimmed = raw.split(b"\x00", 1)[0]
    return trimmed.decode("latin-1", errors="replace")


def read_image_description(data: bytes, offset: int) -> str | None:
    raw = data[offset : offset + 32]
    if raw and all(byte == 0xFF for byte in raw):
        return None
    value = read_string(data, offset, 32)
    return None if value == "" else value


def normalize_dpx_datetime(value: str | None) -> str | None:
    if value is None or len(value) < 11:
        return value
    if value[4] == ":" and value[7] == ":" and value[10] == ":":
        return f"{value[:10]} {value[11:]}"
    return value


def normalize_aspect_ratio(numerator: int, denominator: int) -> tuple[int, int] | None:
    if numerator == 0xFFFFFFFF or denominator == 0xFFFFFFFF:
        return None
    return (numerator, denominator)


def describe_aspect_ratio(aspect_ratio: tuple[int, int] | None) -> str | None:
    if aspect_ratio is None:
        return None
    numerator, denominator = aspect_ratio
    if numerator == 0 and denominator == 0:
        return "undef"
    if denominator == 0:
        return "inf"
    divisor = math.gcd(numerator, denominator)
    return f"{numerator // divisor}:{denominator // divisor}"


def add_non_mutating_gate(
    gates: list[DpxOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        DpxOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="DPX planning is preserve-only; byte emission requires explicit opt-in.",
            evidence_ids=(DPX_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[DpxOutputEmissionGate, ...]) -> bool:
    structural_codes: tuple[DpxEmissionGateCode, ...] = (
        "truncated_dpx_header",
        "unsupported_dpx_signature",
    )
    return any(gate.code in structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[DpxOutputEmissionGate, ...],
) -> tuple[DpxOutputEmissionGate, ...]:
    seen: set[DpxEmissionGateCode] = set()
    unique: list[DpxOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for evidence_id in evidence_ids:
        if evidence_id in unique:
            continue
        unique.append(evidence_id)
    return tuple(unique)
