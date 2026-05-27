"""Source-backed AES-CBC capability planning.

This module records the AES.pm contract without performing AES encryption or
decryption. It validates ExifTool-compatible key, IV, and block boundaries, then
leaves crypto execution behind an explicit future native implementation gate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

AES_BLOCK_SIZE_BYTES = 16
AES_SUPPORTED_KEY_SIZES_BYTES = (16, 24, 32)

type AesCbcOperation = Literal["encrypt", "decrypt"]
type AesCbcPlanStatus = Literal["planned", "unsupported"]
type AesCbcGateStage = Literal["validation", "execution"]
type AesCbcIvSource = Literal[
    "explicit_encrypt_iv",
    "future_secure_random_iv",
    "ciphertext_prefix",
    "not_applicable",
    "unavailable",
]
type AesCbcPaddingMode = Literal[
    "pkcs5_compatible",
    "no_full_block_padding_when_aligned",
    "decryption_padding_removal",
    "padding_not_observable",
]
type AesCbcGateCode = Literal[
    "valid_aes_key_length",
    "invalid_aes_key_length",
    "encrypt_iv_length_valid",
    "invalid_encrypt_iv_length",
    "decrypt_uses_prefixed_iv",
    "decrypt_iv_argument_not_supported",
    "ciphertext_block_length_valid",
    "invalid_ciphertext_block_length",
    "decrypt_short_ciphertext_maps_to_empty",
    "crypto_operation_not_requested",
    "crypto_execution_not_enabled",
    "native_aes_cbc_crypto_not_implemented",
]

AES_HEADER_SOURCE = "codec.aes.header"
AES_CRYPT_CONTRACT_SOURCE = "codec.aes.crypt_contract"
AES_KEY_LENGTH_SOURCE = "codec.aes.key_length"
AES_ENCRYPT_IV_SOURCE = "codec.aes.encrypt_iv"
AES_PADDING_SOURCE = "codec.aes.padding"
AES_DECRYPT_INPUT_SOURCE = "codec.aes.decrypt_input"
AES_BLOCK_LOOP_SOURCE = "codec.aes.block_loop"
AES_DECRYPT_PADDING_SOURCE = "codec.aes.decrypt_padding"
AES_CBC_CIPHER_SOURCE = "codec.aes.cbc_cipher"
AES_POD_SOURCE = "codec.aes.pod"
AES_NATIVE_BOUNDARY_SOURCE = "codec.aes.native_boundary"

AES_CBC_CODEC_PLAN_EVIDENCE_IDS = (
    AES_HEADER_SOURCE,
    AES_CRYPT_CONTRACT_SOURCE,
    AES_KEY_LENGTH_SOURCE,
    AES_ENCRYPT_IV_SOURCE,
    AES_PADDING_SOURCE,
    AES_DECRYPT_INPUT_SOURCE,
    AES_BLOCK_LOOP_SOURCE,
    AES_DECRYPT_PADDING_SOURCE,
    AES_CBC_CIPHER_SOURCE,
    AES_POD_SOURCE,
    AES_NATIVE_BOUNDARY_SOURCE,
)


class AesCbcCodecPlanBlocked(Exception):
    """Raised when execution is requested from a plan-only AES-CBC surface."""


@dataclass(frozen=True)
class AesCbcOperationRequest:
    operation: AesCbcOperation
    data: bytes
    iv: bytes | None = None
    no_padding: bool = False


@dataclass(frozen=True)
class AesCbcPlanGate:
    code: AesCbcGateCode
    stage: AesCbcGateStage
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcResponsibility:
    concern: str
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcKeyPlan:
    key_length_bytes: int
    supported: bool
    aes_strength_bits: int | None
    rounds: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcIvPlan:
    source: AesCbcIvSource
    length_bytes: int | None
    valid: bool
    requires_random_iv: bool
    secure_random_required_for_future_execution: bool
    exiftool_seed_boundary: str | None
    iv_bytes: bytes | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcPayloadPlan:
    operation: AesCbcOperation | None
    original_payload: bytes
    cbc_payload: bytes
    block_size_bytes: int
    block_aligned: bool
    block_count: int
    padding_mode: AesCbcPaddingMode
    padding_length_bytes: int | None
    predicted_length_with_iv_bytes: int | None
    decrypts_to_empty_without_crypto: bool
    preserves_input_bytes: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcDependencyBoundary:
    executes_crypto: bool
    native_crypto_implemented: bool
    external_crypto_dependency_allowed: bool
    future_native_implementation_required: bool
    security_boundary: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcCompatibilityPlan:
    oracle_module: str
    supported_modes: tuple[str, ...]
    supported_key_sizes_bytes: tuple[int, ...]
    block_size_bytes: int
    future_native_steps: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AesCbcCodecPlan:
    status: AesCbcPlanStatus
    key_plan: AesCbcKeyPlan
    operation_request: AesCbcOperationRequest | None
    iv_plan: AesCbcIvPlan
    payload_plan: AesCbcPayloadPlan
    dependency_boundary: AesCbcDependencyBoundary
    compatibility_plan: AesCbcCompatibilityPlan
    operation_gates: tuple[AesCbcPlanGate, ...]
    responsibilities: tuple[AesCbcResponsibility, ...]
    evidence_ids: tuple[str, ...]

    @property
    def validation_blockers(self) -> tuple[AesCbcPlanGate, ...]:
        return tuple(
            gate for gate in self.operation_gates if gate.stage == "validation" and not gate.passed
        )

    @property
    def execution_blockers(self) -> tuple[AesCbcPlanGate, ...]:
        return tuple(
            gate for gate in self.operation_gates if gate.stage == "execution" and not gate.passed
        )

    @property
    def can_execute_crypto(self) -> bool:
        return not self.validation_blockers and not self.execution_blockers

    def execute(self) -> bytes:
        if self.execution_blockers:
            codes = ", ".join(gate.code for gate in self.execution_blockers)
            raise AesCbcCodecPlanBlocked(codes)
        if self.validation_blockers:
            codes = ", ".join(gate.code for gate in self.validation_blockers)
            raise AesCbcCodecPlanBlocked(codes)
        raise AesCbcCodecPlanBlocked("native_aes_cbc_crypto_not_implemented")


def build_aes_cbc_codec_plan(
    key: bytes,
    operation_request: AesCbcOperationRequest | None = None,
    *,
    allow_crypto_execution: bool = False,
) -> AesCbcCodecPlan:
    request = _copy_request(operation_request)
    key_plan = _build_key_plan(key)
    iv_plan = _build_iv_plan(request)
    payload_plan = _build_payload_plan(request)
    dependency_boundary = _build_dependency_boundary()
    compatibility_plan = _build_compatibility_plan()
    operation_gates = _build_operation_gates(
        key_plan=key_plan,
        request=request,
        iv_plan=iv_plan,
        payload_plan=payload_plan,
        allow_crypto_execution=allow_crypto_execution,
        dependency_boundary=dependency_boundary,
    )
    validation_blockers = tuple(
        gate for gate in operation_gates if gate.stage == "validation" and not gate.passed
    )

    return AesCbcCodecPlan(
        status="unsupported" if validation_blockers else "planned",
        key_plan=key_plan,
        operation_request=request,
        iv_plan=iv_plan,
        payload_plan=payload_plan,
        dependency_boundary=dependency_boundary,
        compatibility_plan=compatibility_plan,
        operation_gates=operation_gates,
        responsibilities=_build_responsibilities(request),
        evidence_ids=AES_CBC_CODEC_PLAN_EVIDENCE_IDS,
    )


def _copy_request(request: AesCbcOperationRequest | None) -> AesCbcOperationRequest | None:
    if request is None:
        return None
    return replace(
        request,
        data=bytes(request.data),
        iv=None if request.iv is None else bytes(request.iv),
    )


def _build_key_plan(key: bytes) -> AesCbcKeyPlan:
    key_length = len(key)
    if key_length not in AES_SUPPORTED_KEY_SIZES_BYTES:
        return AesCbcKeyPlan(
            key_length_bytes=key_length,
            supported=False,
            aes_strength_bits=None,
            rounds=None,
            evidence_ids=(AES_KEY_LENGTH_SOURCE, AES_BLOCK_LOOP_SOURCE, AES_POD_SOURCE),
        )

    words = key_length // 4
    return AesCbcKeyPlan(
        key_length_bytes=key_length,
        supported=True,
        aes_strength_bits=key_length * 8,
        rounds=words + 6,
        evidence_ids=(AES_KEY_LENGTH_SOURCE, AES_BLOCK_LOOP_SOURCE, AES_POD_SOURCE),
    )


def _build_iv_plan(request: AesCbcOperationRequest | None) -> AesCbcIvPlan:
    if request is None:
        return AesCbcIvPlan(
            source="not_applicable",
            length_bytes=None,
            valid=True,
            requires_random_iv=False,
            secure_random_required_for_future_execution=False,
            exiftool_seed_boundary=None,
            iv_bytes=None,
            evidence_ids=(AES_CRYPT_CONTRACT_SOURCE,),
        )

    if request.operation == "encrypt":
        if request.iv is None:
            return AesCbcIvPlan(
                source="future_secure_random_iv",
                length_bytes=None,
                valid=True,
                requires_random_iv=True,
                secure_random_required_for_future_execution=True,
                exiftool_seed_boundary=(
                    "AES.pm seeds Perl rand with time and process id; modern execution must use "
                    "secure random bytes instead."
                ),
                iv_bytes=None,
                evidence_ids=(AES_ENCRYPT_IV_SOURCE, AES_POD_SOURCE),
            )
        return AesCbcIvPlan(
            source="explicit_encrypt_iv",
            length_bytes=len(request.iv),
            valid=len(request.iv) == AES_BLOCK_SIZE_BYTES,
            requires_random_iv=False,
            secure_random_required_for_future_execution=False,
            exiftool_seed_boundary=None,
            iv_bytes=request.iv,
            evidence_ids=(AES_ENCRYPT_IV_SOURCE, AES_POD_SOURCE),
        )

    if request.iv is not None:
        return AesCbcIvPlan(
            source="unavailable",
            length_bytes=len(request.iv),
            valid=False,
            requires_random_iv=False,
            secure_random_required_for_future_execution=False,
            exiftool_seed_boundary=None,
            iv_bytes=None,
            evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
        )

    if (
        len(request.data) >= AES_BLOCK_SIZE_BYTES * 2
        and len(request.data) % AES_BLOCK_SIZE_BYTES == 0
    ):
        return AesCbcIvPlan(
            source="ciphertext_prefix",
            length_bytes=AES_BLOCK_SIZE_BYTES,
            valid=True,
            requires_random_iv=False,
            secure_random_required_for_future_execution=False,
            exiftool_seed_boundary=None,
            iv_bytes=request.data[:AES_BLOCK_SIZE_BYTES],
            evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
        )

    return AesCbcIvPlan(
        source="unavailable",
        length_bytes=None,
        valid=True,
        requires_random_iv=False,
        secure_random_required_for_future_execution=False,
        exiftool_seed_boundary=None,
        iv_bytes=None,
        evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
    )


def _build_payload_plan(request: AesCbcOperationRequest | None) -> AesCbcPayloadPlan:
    if request is None:
        return AesCbcPayloadPlan(
            operation=None,
            original_payload=b"",
            cbc_payload=b"",
            block_size_bytes=AES_BLOCK_SIZE_BYTES,
            block_aligned=True,
            block_count=0,
            padding_mode="padding_not_observable",
            padding_length_bytes=None,
            predicted_length_with_iv_bytes=None,
            decrypts_to_empty_without_crypto=False,
            preserves_input_bytes=True,
            evidence_ids=(AES_CRYPT_CONTRACT_SOURCE,),
        )

    data = request.data
    if request.operation == "encrypt":
        part_len = len(data) % AES_BLOCK_SIZE_BYTES
        pad_len = AES_BLOCK_SIZE_BYTES - part_len
        padding_length = 0 if pad_len == AES_BLOCK_SIZE_BYTES and request.no_padding else pad_len
        predicted_length = AES_BLOCK_SIZE_BYTES + len(data) + padding_length
        return AesCbcPayloadPlan(
            operation="encrypt",
            original_payload=data,
            cbc_payload=data,
            block_size_bytes=AES_BLOCK_SIZE_BYTES,
            block_aligned=True,
            block_count=(len(data) + padding_length) // AES_BLOCK_SIZE_BYTES,
            padding_mode=(
                "no_full_block_padding_when_aligned" if padding_length == 0 else "pkcs5_compatible"
            ),
            padding_length_bytes=padding_length,
            predicted_length_with_iv_bytes=predicted_length,
            decrypts_to_empty_without_crypto=False,
            preserves_input_bytes=True,
            evidence_ids=(AES_ENCRYPT_IV_SOURCE, AES_PADDING_SOURCE, AES_BLOCK_LOOP_SOURCE),
        )

    aligned = len(data) % AES_BLOCK_SIZE_BYTES == 0
    short_ciphertext = aligned and len(data) < AES_BLOCK_SIZE_BYTES * 2
    cbc_payload = data[AES_BLOCK_SIZE_BYTES:] if aligned and not short_ciphertext else b""
    return AesCbcPayloadPlan(
        operation="decrypt",
        original_payload=data,
        cbc_payload=cbc_payload,
        block_size_bytes=AES_BLOCK_SIZE_BYTES,
        block_aligned=aligned,
        block_count=len(cbc_payload) // AES_BLOCK_SIZE_BYTES,
        padding_mode=(
            "padding_not_observable" if request.no_padding else "decryption_padding_removal"
        ),
        padding_length_bytes=None,
        predicted_length_with_iv_bytes=None,
        decrypts_to_empty_without_crypto=short_ciphertext,
        preserves_input_bytes=True,
        evidence_ids=(
            AES_DECRYPT_INPUT_SOURCE,
            AES_DECRYPT_PADDING_SOURCE,
            AES_BLOCK_LOOP_SOURCE,
        ),
    )


def _build_dependency_boundary() -> AesCbcDependencyBoundary:
    return AesCbcDependencyBoundary(
        executes_crypto=False,
        native_crypto_implemented=False,
        external_crypto_dependency_allowed=False,
        future_native_implementation_required=True,
        security_boundary=(
            "Plan-only surface: do not call external crypto packages or AES.pm. Future native "
            "execution must provide constant-time reviewed AES-CBC and secure IV generation."
        ),
        evidence_ids=(
            AES_HEADER_SOURCE,
            AES_CRYPT_CONTRACT_SOURCE,
            AES_NATIVE_BOUNDARY_SOURCE,
        ),
    )


def _build_compatibility_plan() -> AesCbcCompatibilityPlan:
    return AesCbcCompatibilityPlan(
        oracle_module="Image::ExifTool::AES",
        supported_modes=("AES-CBC",),
        supported_key_sizes_bytes=AES_SUPPORTED_KEY_SIZES_BYTES,
        block_size_bytes=AES_BLOCK_SIZE_BYTES,
        future_native_steps=(
            "Port KeyExpansion round-count behavior for 16, 24, and 32 byte keys.",
            "Implement Cipher and InvCipher against 16-byte CBC state transitions.",
            "Use secure random IV generation instead of the AES.pm srand boundary.",
            "Retain AES.pm padding and IV-prefix compatibility tests before enabling execution.",
        ),
        evidence_ids=(
            AES_KEY_LENGTH_SOURCE,
            AES_CBC_CIPHER_SOURCE,
            AES_ENCRYPT_IV_SOURCE,
            AES_PADDING_SOURCE,
            AES_POD_SOURCE,
        ),
    )


def _build_operation_gates(
    *,
    key_plan: AesCbcKeyPlan,
    request: AesCbcOperationRequest | None,
    iv_plan: AesCbcIvPlan,
    payload_plan: AesCbcPayloadPlan,
    allow_crypto_execution: bool,
    dependency_boundary: AesCbcDependencyBoundary,
) -> tuple[AesCbcPlanGate, ...]:
    gates: list[AesCbcPlanGate] = []
    if key_plan.supported:
        gates.append(
            AesCbcPlanGate(
                code="valid_aes_key_length",
                stage="validation",
                passed=True,
                reason="Key length matches AES.pm-supported 16, 24, or 32 byte sizes.",
                evidence_ids=(AES_KEY_LENGTH_SOURCE, AES_POD_SOURCE),
            )
        )
    else:
        gates.append(
            AesCbcPlanGate(
                code="invalid_aes_key_length",
                stage="validation",
                passed=False,
                reason=f"Invalid AES key length ({key_plan.key_length_bytes}).",
                evidence_ids=(AES_KEY_LENGTH_SOURCE,),
            )
        )

    if request is None:
        gates.append(
            AesCbcPlanGate(
                code="crypto_operation_not_requested",
                stage="execution",
                passed=False,
                reason="No encrypt or decrypt request was supplied; the capability plan is inert.",
                evidence_ids=(AES_CRYPT_CONTRACT_SOURCE, AES_NATIVE_BOUNDARY_SOURCE),
            )
        )
        return tuple(gates)

    if request.operation == "encrypt":
        gates.append(
            AesCbcPlanGate(
                code="encrypt_iv_length_valid" if iv_plan.valid else "invalid_encrypt_iv_length",
                stage="validation",
                passed=iv_plan.valid,
                reason=(
                    "Encryption IV is absent for future secure generation or exactly 16 bytes."
                    if iv_plan.valid
                    else f"Encryption IV must be 16 bytes, got {iv_plan.length_bytes}."
                ),
                evidence_ids=(AES_ENCRYPT_IV_SOURCE, AES_POD_SOURCE),
            )
        )
    else:
        if request.iv is not None:
            gates.append(
                AesCbcPlanGate(
                    code="decrypt_iv_argument_not_supported",
                    stage="validation",
                    passed=False,
                    reason="AES.pm decryption reads the IV from the first 16 ciphertext bytes.",
                    evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
                )
            )
        elif payload_plan.decrypts_to_empty_without_crypto:
            gates.append(
                AesCbcPlanGate(
                    code="decrypt_short_ciphertext_maps_to_empty",
                    stage="validation",
                    passed=True,
                    reason="AES.pm maps aligned ciphertext shorter than 32 bytes to empty text.",
                    evidence_ids=(AES_DECRYPT_INPUT_SOURCE,),
                )
            )
        else:
            gates.append(
                AesCbcPlanGate(
                    code="ciphertext_block_length_valid"
                    if payload_plan.block_aligned
                    else "invalid_ciphertext_block_length",
                    stage="validation",
                    passed=payload_plan.block_aligned,
                    reason=(
                        "Ciphertext length is a whole number of 16-byte AES blocks."
                        if payload_plan.block_aligned
                        else "Ciphertext length is not a whole number of 16-byte AES blocks."
                    ),
                    evidence_ids=(AES_DECRYPT_INPUT_SOURCE,),
                )
            )
            if payload_plan.block_aligned and len(request.data) >= AES_BLOCK_SIZE_BYTES * 2:
                gates.append(
                    AesCbcPlanGate(
                        code="decrypt_uses_prefixed_iv",
                        stage="validation",
                        passed=True,
                        reason="The first 16 ciphertext bytes are planned as the CBC IV.",
                        evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
                    )
                )

    if not allow_crypto_execution:
        gates.append(
            AesCbcPlanGate(
                code="crypto_execution_not_enabled",
                stage="execution",
                passed=False,
                reason="Crypto execution is disabled by default for this non-mutating planner.",
                evidence_ids=(AES_NATIVE_BOUNDARY_SOURCE,),
            )
        )
    elif not dependency_boundary.native_crypto_implemented:
        gates.append(
            AesCbcPlanGate(
                code="native_aes_cbc_crypto_not_implemented",
                stage="execution",
                passed=False,
                reason="Native AES-CBC execution is intentionally not implemented in this slice.",
                evidence_ids=(AES_NATIVE_BOUNDARY_SOURCE, AES_CBC_CIPHER_SOURCE),
            )
        )

    return tuple(gates)


def _build_responsibilities(
    request: AesCbcOperationRequest | None,
) -> tuple[AesCbcResponsibility, ...]:
    responsibilities = [
        AesCbcResponsibility(
            concern="key_size_validation",
            detail="Support only AES.pm key lengths of 16, 24, and 32 bytes.",
            evidence_ids=(AES_KEY_LENGTH_SOURCE, AES_POD_SOURCE),
        ),
        AesCbcResponsibility(
            concern="fixed_block_size",
            detail="Plan all AES-CBC conversion in fixed 16-byte blocks.",
            evidence_ids=(AES_CRYPT_CONTRACT_SOURCE, AES_BLOCK_LOOP_SOURCE),
        ),
        AesCbcResponsibility(
            concern="cbc_state_boundary",
            detail="Preserve CBC state semantics for future Cipher and InvCipher parity.",
            evidence_ids=(AES_CBC_CIPHER_SOURCE,),
        ),
        AesCbcResponsibility(
            concern="no_crypto_execution",
            detail="Do not encrypt, decrypt, call AES.pm, or call external crypto packages.",
            evidence_ids=(AES_NATIVE_BOUNDARY_SOURCE,),
        ),
        AesCbcResponsibility(
            concern="future_native_crypto_compatibility",
            detail="Keep AES.pm-compatible IV prefixing and padding as source-backed requirements.",
            evidence_ids=(AES_POD_SOURCE, AES_PADDING_SOURCE, AES_DECRYPT_PADDING_SOURCE),
        ),
    ]
    if request is not None and request.operation == "encrypt":
        responsibilities.append(
            AesCbcResponsibility(
                concern="encrypt_iv_responsibility",
                detail="Use a supplied 16-byte IV or require future secure random IV generation.",
                evidence_ids=(AES_ENCRYPT_IV_SOURCE, AES_POD_SOURCE),
            )
        )
    if request is not None and request.operation == "decrypt":
        responsibilities.append(
            AesCbcResponsibility(
                concern="decrypt_iv_prefix_responsibility",
                detail="Read the CBC IV from the leading 16 ciphertext bytes when present.",
                evidence_ids=(AES_DECRYPT_INPUT_SOURCE, AES_POD_SOURCE),
            )
        )
    return tuple(responsibilities)
