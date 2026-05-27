"""Typed bytecode schema for safe-expression compilation and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.safe_expression.exiftool_compat import ExifToolFunction

type RegisterName = str
type InputName = str
type SelfContextKey = str
type RuntimeContextNamespace = str
type NumericOperator = Literal["add", "sub", "mul", "div", "mod", "pow"]
type NumericUnaryOperator = Literal["neg", "pos"]
type BitwiseOperator = Literal["bit_and", "bit_or", "bit_xor", "shift_left", "shift_right"]
type PairwiseListOperator = Literal["sub"]
type SplitSeparatorKind = Literal["literal", "regex"]
type PackTemplate = Literal["C*", "H*", "N", "N*"]
type UnpackTemplate = Literal[
    "C*",
    "H*",
    "H2H2",
    "N",
    "NN",
    "N*",
    "V",
    "V*",
    "VfVVf6c4lCCcclf4Vvv",
    "x2nn",
    "x4N",
    "x20N4xZ*",
]
type LivePhotoInfoTemplateToken = Literal["V", "f", "c", "C", "l", "v"]
LIVE_PHOTO_INFO_TEMPLATE: tuple[LivePhotoInfoTemplateToken, ...] = (
    "V",
    "f",
    "V",
    "V",
    "f",
    "f",
    "f",
    "f",
    "f",
    "f",
    "c",
    "c",
    "c",
    "c",
    "l",
    "C",
    "C",
    "c",
    "c",
    "l",
    "f",
    "f",
    "f",
    "f",
    "V",
    "v",
    "v",
)
type UnaryNumericFunction = Literal["int", "log", "exp", "sqrt"]
type BinaryNumericFunction = Literal["atan2"]
type BinaryReadKind = Literal["uint8", "int16", "uint16", "uint32", "float32", "float64"]
type BinaryWriteKind = Literal["int16"]
type UnaryScalarFunction = Literal[
    "abs",
    "length",
    "chr",
    "defined",
    "hex",
    "getgrgid",
    "getpwuid",
    "oct",
    "is_int",
    "is_float",
    "lc",
    "ord",
    "ref",
    "uc",
    "ucfirst",
]
type ComparisonOperator = Literal[
    "num_eq",
    "num_ne",
    "lt",
    "le",
    "gt",
    "ge",
    "str_eq",
    "str_ne",
    "str_lt",
    "str_le",
    "str_gt",
    "str_ge",
]
type ScalarReferenceScalar = str | int | float | bool | None


@dataclass(frozen=True)
class ScalarReferenceValue:
    value: ScalarReferenceScalar


@dataclass(frozen=True)
class ArrayReferenceValue:
    values: list[VmScalar]


@dataclass(frozen=True)
class HashReferenceEntry:
    key: str
    value: VmScalar


@dataclass(frozen=True)
class HashReferenceValue:
    entries: tuple[HashReferenceEntry, ...]


type VmScalar = (
    ScalarReferenceScalar | ScalarReferenceValue | ArrayReferenceValue | HashReferenceValue
)
type VmValue = VmScalar | list[VmScalar]
type VmRegisters = dict[RegisterName, VmValue]
type VmInputs = dict[InputName, VmValue]
type InterpolationSegment = InterpolationLiteral | InterpolationValue


@dataclass(frozen=True)
class LoadConst:
    target: RegisterName
    value: VmValue


@dataclass(frozen=True)
class LoadInput:
    target: RegisterName
    name: InputName


@dataclass(frozen=True)
class LoadSelfContext:
    target: RegisterName
    key: SelfContextKey


@dataclass(frozen=True)
class StaticContextPathSegment:
    value: str


@dataclass(frozen=True)
class DynamicContextPathSegment:
    register: RegisterName


type ContextPathSegment = StaticContextPathSegment | DynamicContextPathSegment


@dataclass(frozen=True)
class LoadContextPath:
    target: RegisterName
    namespace: RuntimeContextNamespace
    segments: list[ContextPathSegment]


@dataclass(frozen=True)
class LoadHashPath:
    target: RegisterName
    source: RegisterName
    segments: list[ContextPathSegment]


@dataclass(frozen=True)
class StoreContextPath:
    target: RegisterName
    namespace: RuntimeContextNamespace
    segments: list[ContextPathSegment]
    value: RegisterName


@dataclass(frozen=True)
class LoadIndex:
    target: RegisterName
    source: RegisterName
    index: int


@dataclass(frozen=True)
class LoadDynamicIndex:
    target: RegisterName
    source: RegisterName
    index: RegisterName


@dataclass(frozen=True)
class BuildList:
    target: RegisterName
    values: list[RegisterName]


@dataclass(frozen=True)
class RegexMatch:
    target: RegisterName
    value: RegisterName
    pattern: str
    ignore_case: bool = False
    dot_matches_newline: bool = False


@dataclass(frozen=True)
class RegexSubstitute:
    target: RegisterName
    value: RegisterName
    pattern: str
    replacement: str
    global_substitution: bool = False
    ignore_case: bool = False
    dot_matches_newline: bool = False


@dataclass(frozen=True)
class Transliterate:
    target: RegisterName
    value: RegisterName
    source_chars: str
    replacement_chars: str


@dataclass(frozen=True)
class MakeScalarReference:
    target: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class DereferenceScalar:
    target: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class NumericBinary:
    target: RegisterName
    left: RegisterName
    operator: NumericOperator
    right: RegisterName


@dataclass(frozen=True)
class NumericUnary:
    target: RegisterName
    operator: NumericUnaryOperator
    value: RegisterName


@dataclass(frozen=True)
class BitwiseBinary:
    target: RegisterName
    left: RegisterName
    operator: BitwiseOperator
    right: RegisterName


@dataclass(frozen=True)
class NumericBinaryIfTruthy:
    target: RegisterName
    condition: RegisterName
    left: RegisterName
    operator: NumericOperator
    right: RegisterName
    false_value: VmValue


@dataclass(frozen=True)
class Compare:
    target: RegisterName
    left: RegisterName
    operator: ComparisonOperator
    right: RegisterName


@dataclass(frozen=True)
class Ternary:
    target: RegisterName
    condition: RegisterName
    true_value: RegisterName
    false_value: RegisterName


@dataclass(frozen=True)
class TruthyAnd:
    target: RegisterName
    left: RegisterName
    right: RegisterName


@dataclass(frozen=True)
class TruthyNot:
    target: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class LazyTruthyAnd:
    target: RegisterName
    left: RegisterName
    right_instructions: list[VmInstruction]
    right_result: RegisterName


@dataclass(frozen=True)
class LazyTruthyOr:
    target: RegisterName
    left: RegisterName
    right_instructions: list[VmInstruction]
    right_result: RegisterName


@dataclass(frozen=True)
class StringConcat:
    target: RegisterName
    left: RegisterName
    right: RegisterName


@dataclass(frozen=True)
class StringRepeat:
    target: RegisterName
    value: RegisterName
    count: RegisterName


@dataclass(frozen=True)
class SplitString:
    target: RegisterName
    separator: RegisterName
    value: RegisterName
    separator_kind: SplitSeparatorKind = "literal"
    limit: RegisterName | None = None


@dataclass(frozen=True)
class JoinString:
    target: RegisterName
    separator: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class ListLength:
    target: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class ReverseList:
    target: RegisterName
    value: RegisterName


@dataclass(frozen=True)
class MapList:
    target: RegisterName
    value: RegisterName
    item_register: RegisterName
    item_instructions: list[VmInstruction]
    item_result: RegisterName


@dataclass(frozen=True)
class SpliceList:
    target: RegisterName
    value: RegisterName
    start: RegisterName
    length: RegisterName


@dataclass(frozen=True)
class ListPushScalar:
    target: RegisterName
    value: RegisterName
    item: RegisterName


@dataclass(frozen=True)
class PairwiseListNumeric:
    target: RegisterName
    left: RegisterName
    operator: PairwiseListOperator
    right: RegisterName


@dataclass(frozen=True)
class ListIndexNumericTransform:
    target: RegisterName
    value: RegisterName
    index: int
    operator: NumericOperator
    operand: RegisterName


@dataclass(frozen=True)
class ListIndexBitwiseTransform:
    target: RegisterName
    value: RegisterName
    index: int
    operator: BitwiseOperator
    operand: RegisterName


@dataclass(frozen=True)
class ListIndexSet:
    target: RegisterName
    value: RegisterName
    index: int
    item: RegisterName


@dataclass(frozen=True)
class Substr:
    target: RegisterName
    value: RegisterName
    start: RegisterName
    length: RegisterName | None


@dataclass(frozen=True)
class UnpackBinary:
    target: RegisterName
    template: UnpackTemplate
    value: RegisterName
    skip_bytes: int = 0


@dataclass(frozen=True)
class UnpackHexGroups:
    target: RegisterName
    value: RegisterName
    nibble_lengths: list[int]


@dataclass(frozen=True)
class PackBinary:
    target: RegisterName
    template: PackTemplate
    values: list[RegisterName]


@dataclass(frozen=True)
class ReadBinaryValue:
    target: RegisterName
    value: RegisterName
    offset: RegisterName
    kind: BinaryReadKind
    byte_order: RegisterName | None = None


@dataclass(frozen=True)
class PackBinaryValue:
    target: RegisterName
    value: RegisterName
    kind: BinaryWriteKind
    byte_order: RegisterName


@dataclass(frozen=True)
class PrintSpatialFrequencyResponse:
    target: RegisterName
    value: RegisterName
    byte_order: RegisterName


@dataclass(frozen=True)
class Sprintf:
    target: RegisterName
    template: str
    values: list[RegisterName]


@dataclass(frozen=True)
class InterpolateString:
    target: RegisterName
    segments: list[InterpolationSegment]


@dataclass(frozen=True)
class InterpolationLiteral:
    text: str


@dataclass(frozen=True)
class InterpolationValue:
    value: RegisterName


@dataclass(frozen=True)
class UnaryNumericCall:
    target: RegisterName
    function: UnaryNumericFunction
    value: RegisterName


@dataclass(frozen=True)
class BinaryNumericCall:
    target: RegisterName
    function: BinaryNumericFunction
    left: RegisterName
    right: RegisterName


@dataclass(frozen=True)
class UnaryScalarCall:
    target: RegisterName
    function: UnaryScalarFunction
    value: RegisterName


@dataclass(frozen=True)
class ExifToolFunctionCall:
    target: RegisterName
    function: ExifToolFunction
    values: list[ExifToolCallArgument]


@dataclass(frozen=True)
class ExifToolScalarArgument:
    value: RegisterName


@dataclass(frozen=True)
class ExifToolVariadicArgument:
    value: RegisterName


type ExifToolCallArgument = ExifToolScalarArgument | ExifToolVariadicArgument


@dataclass(frozen=True)
class LazyTernary:
    target: RegisterName
    condition: RegisterName
    true_instructions: list[VmInstruction]
    true_result: RegisterName
    false_instructions: list[VmInstruction]
    false_result: RegisterName


@dataclass(frozen=True)
class WhileLoop:
    condition_instructions: list[VmInstruction]
    condition_result: RegisterName
    body_instructions: list[VmInstruction]
    max_iterations: int = 100_000


type VmInstruction = (
    LoadConst
    | LoadInput
    | LoadSelfContext
    | LoadContextPath
    | LoadHashPath
    | StoreContextPath
    | LoadIndex
    | LoadDynamicIndex
    | BuildList
    | RegexMatch
    | RegexSubstitute
    | Transliterate
    | MakeScalarReference
    | DereferenceScalar
    | NumericBinary
    | NumericUnary
    | BitwiseBinary
    | NumericBinaryIfTruthy
    | Compare
    | Ternary
    | TruthyAnd
    | TruthyNot
    | LazyTruthyAnd
    | LazyTruthyOr
    | StringConcat
    | StringRepeat
    | SplitString
    | JoinString
    | ListLength
    | ReverseList
    | MapList
    | SpliceList
    | ListPushScalar
    | PairwiseListNumeric
    | ListIndexNumericTransform
    | ListIndexBitwiseTransform
    | ListIndexSet
    | Substr
    | UnpackBinary
    | UnpackHexGroups
    | PackBinary
    | ReadBinaryValue
    | PackBinaryValue
    | PrintSpatialFrequencyResponse
    | Sprintf
    | InterpolateString
    | UnaryNumericCall
    | BinaryNumericCall
    | UnaryScalarCall
    | ExifToolFunctionCall
    | LazyTernary
    | WhileLoop
)


@dataclass(frozen=True)
class SafeExpressionProgram:
    instructions: list[VmInstruction]
    result: RegisterName


@dataclass(frozen=True)
class ContextUpdate:
    namespace: RuntimeContextNamespace
    path: list[str]
    value: VmValue


@dataclass(frozen=True)
class FoundTagUpdate:
    name: str
    value: VmValue


@dataclass(frozen=True)
class SafeExpressionResult:
    value: VmValue
    context_updates: list[ContextUpdate]
    found_tags: list[FoundTagUpdate]


type VmContextUpdates = list[ContextUpdate]
type VmFoundTags = list[FoundTagUpdate]
