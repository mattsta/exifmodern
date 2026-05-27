"""Typed AST models for safe-expression parsing and compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from exifmodern.safe_expression.bytecode import (
    SplitSeparatorKind,
    UnpackTemplate,
    VmInstruction,
    VmScalar,
)

type AstNode = (
    NumberLiteral
    | StringLiteral
    | ListLiteral
    | RegexLiteral
    | ValInterpolatedString
    | UnitSuffixExpression
    | UndefLiteral
    | ValReference
    | ValListReference
    | RawListReference
    | ScalarReferenceExpression
    | ScalarDereferenceExpression
    | DynamicValReference
    | PrtReference
    | DynamicPrtReference
    | SelfReference
    | TagInfoReference
    | SelfContextReference
    | SelfContextAssignment
    | PackageScalarReference
    | PackageScalarAssignment
    | LocalScalarContextReference
    | SystemOsReference
    | TagReference
    | LocalArrayReference
    | LocalArraySliceReference
    | LocalArrayValue
    | LocalScalarReference
    | CurrentItemReference
    | FunctionCall
    | MapExpression
    | RegexMatchExpression
    | StatementProgram
    | ComparisonExpression
    | BitwiseExpression
    | NumericUnaryExpression
    | NumericExpression
    | StringConcatExpression
    | StringRepeatExpression
    | TruthyAndExpression
    | TruthyNotExpression
    | TruthyOrExpression
    | TernaryExpression
)
type TransformNode = (
    AstNode
    | RequiredModule
    | PairwiseArrayRef
    | PairwiseArraySubtract
    | PairwiseArrayRange
    | LocalScalarTarget
    | LocalScalarTargetList
    | ExpressionList
    | ForeachLiteralValues
    | ArrayConditionalTransformTail
    | ForeachReturnBlock
    | ForeachArrayName
    | ForeachArraySetBlock
    | StaticRuntimeContextKey
    | DynamicRuntimeContextKey
    | RuntimeContextPath
)
type NumericSymbol = Literal["+", "-", "*", "/", "%", "**"]
type NumericUnarySymbol = Literal["+", "-"]
type BitwiseSymbol = Literal["&", "|", "^", "<<", ">>"]
type ListTransformSymbol = Literal["=", "+=", "-=", "/=", "*="]
type ListIndexBitwiseTransformSymbol = Literal["&=", "|=", "^="]
type ComparisonSymbol = Literal[
    "==", "!=", "<", "<=", ">", ">=", "eq", "ne", "lt", "le", "gt", "ge"
]
type InstructionBuilder = Callable[[str], VmInstruction]
type SafeInputName = Literal["$val", "$prt", "@raw", "$byte_order", "$^O"]
type StringTemplateSegment = (
    StringTemplateLiteral
    | StringTemplateValue
    | StringTemplateLocalArrayValue
    | StringTemplateLocalScalarValue
    | StringTemplateLocalScalarContextValue
    | StringTemplateCurrentItem
)
type LocalArrayName = str
type LocalArrayRegisters = dict[LocalArrayName, str]
type LocalScalarName = str
type LocalScalarRegisters = dict[LocalScalarName, str]
type RuntimeContextInputName = str
type RuntimeContextNamespace = str
type InputOverrides = dict[RuntimeContextInputName, str]
EXTERNAL_LOCAL_SCALAR_INPUT_NAMES: tuple[LocalScalarName, ...] = (
    "count",
    "format",
    "index",
    "valPt",
)
type ProgramStatement = (
    LocalArrayAssignment
    | LocalArrayEmptyAssignment
    | LocalArrayTransform
    | LocalArraySliceTransform
    | LocalArrayConditionalTransform
    | LocalArrayIndexedTransform
    | LocalArrayIndexedBitwiseTransform
    | LocalArrayIndexedAssignment
    | LocalArrayIndexedTransformPair
    | LocalArrayPairwiseTransform
    | ForeachConditionalReturnStatement
    | LocalArrayPushWhileStatement
    | InputAssignment
    | InputAssignmentIfStatement
    | InputSubstitutionStatement
    | CurrentItemAssignment
    | CurrentItemSubstitutionStatement
    | CurrentItemTransliterationStatement
    | LocalScalarAssignment
    | LocalScalarAssignmentIfStatement
    | LocalScalarTupleAssignment
    | LocalScalarTupleListAssignment
    | LocalScalarAppendIfStatement
    | LocalScalarNumericAssignmentIfStatement
    | LocalScalarNumericAssignmentWhileStatement
    | FunctionCallStatement
    | ToFloatValListStatement
    | ByteOrderAssignmentStatement
    | ByteOrderToggleStatement
    | ByteOrderToggleIfStatement
    | SelfContextAssignment
    | SelfContextAssignmentIfStatement
    | PackageScalarAssignment
    | PackageScalarAssignmentIfStatement
    | NoOpStatement
    | ReturnIfStatement
    | ReturnUnlessStatement
    | RequiredModule
)


@dataclass(frozen=True)
class NumberLiteral:
    value: int | float


@dataclass(frozen=True)
class StringLiteral:
    value: str


@dataclass(frozen=True)
class ListLiteral:
    values: list[VmScalar]


@dataclass(frozen=True)
class RegexLiteral:
    pattern: str
    ignore_case: bool
    dot_matches_newline: bool


@dataclass(frozen=True)
class ValInterpolatedString:
    segments: list[StringTemplateSegment]


@dataclass(frozen=True)
class UnitSuffixExpression:
    value: ValReference | DynamicValReference
    suffix: str


@dataclass(frozen=True)
class StringTemplateLiteral:
    text: str


@dataclass(frozen=True)
class StringTemplateValue:
    input_name: SafeInputName
    index: int | None


@dataclass(frozen=True)
class StringTemplateLocalArrayValue:
    name: LocalArrayName
    index: int | None


@dataclass(frozen=True)
class StringTemplateLocalScalarValue:
    name: LocalScalarName


@dataclass(frozen=True)
class StringTemplateLocalScalarContextValue:
    name: LocalScalarName
    path: RuntimeContextPath


@dataclass(frozen=True)
class StringTemplateCurrentItem:
    pass


@dataclass(frozen=True)
class UndefLiteral:
    pass


@dataclass(frozen=True)
class ValReference:
    index: int | None


@dataclass(frozen=True)
class ValListReference:
    pass


@dataclass(frozen=True)
class RawListReference:
    pass


@dataclass(frozen=True)
class ScalarReferenceExpression:
    value: (
        ValReference
        | ValListReference
        | LocalScalarReference
        | LocalArrayValue
        | SelfContextReference
        | PackageScalarReference
    )


@dataclass(frozen=True)
class ScalarDereferenceExpression:
    value: ValReference | DynamicValReference | LocalScalarReference


@dataclass(frozen=True)
class DynamicValReference:
    index: AstNode


@dataclass(frozen=True)
class PrtReference:
    index: int | None


@dataclass(frozen=True)
class DynamicPrtReference:
    index: AstNode


@dataclass(frozen=True)
class RequiredModule:
    name: str


@dataclass(frozen=True)
class NoOpStatement:
    reason: str


@dataclass(frozen=True)
class FunctionCallStatement:
    function: FunctionCall


@dataclass(frozen=True)
class SelfReference:
    pass


@dataclass(frozen=True)
class TagInfoReference:
    pass


@dataclass(frozen=True)
class StaticRuntimeContextKey:
    value: str


@dataclass(frozen=True)
class DynamicRuntimeContextKey:
    value: AstNode


type RuntimeContextKey = StaticRuntimeContextKey | DynamicRuntimeContextKey


@dataclass(frozen=True)
class RuntimeContextPath:
    keys: list[RuntimeContextKey]


@dataclass(frozen=True)
class SelfContextReference:
    path: RuntimeContextPath


@dataclass(frozen=True)
class SelfContextAssignment:
    path: RuntimeContextPath
    value: AstNode


@dataclass(frozen=True)
class SelfContextAssignmentIfStatement:
    condition: AstNode
    assignment: SelfContextAssignment


@dataclass(frozen=True)
class PackageScalarReference:
    name: str
    path: RuntimeContextPath | None


@dataclass(frozen=True)
class PackageScalarAssignment:
    name: str
    path: RuntimeContextPath | None
    value: AstNode


@dataclass(frozen=True)
class PackageScalarAssignmentIfStatement:
    condition: AstNode
    assignment: PackageScalarAssignment


@dataclass(frozen=True)
class LocalScalarContextReference:
    name: LocalScalarName
    path: RuntimeContextPath


@dataclass(frozen=True)
class SystemOsReference:
    pass


@dataclass(frozen=True)
class TagReference:
    pass


@dataclass(frozen=True)
class LocalArrayReference:
    name: LocalArrayName
    index: AstNode


@dataclass(frozen=True)
class LocalArraySliceReference:
    name: LocalArrayName
    indexes: list[int]


@dataclass(frozen=True)
class LocalArrayValue:
    name: LocalArrayName


@dataclass(frozen=True)
class LocalScalarReference:
    name: LocalScalarName


@dataclass(frozen=True)
class CurrentItemReference:
    pass


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: list[AstNode]


@dataclass(frozen=True)
class MapExpression:
    expression: AstNode
    source: AstNode


@dataclass(frozen=True)
class RegexMatchExpression:
    value: AstNode
    regex: RegexLiteral


@dataclass(frozen=True)
class ComparisonExpression:
    left: AstNode
    operator: ComparisonSymbol
    right: AstNode


@dataclass(frozen=True)
class BitwiseExpression:
    left: AstNode
    operator: BitwiseSymbol
    right: AstNode


@dataclass(frozen=True)
class NumericUnaryExpression:
    operator: NumericUnarySymbol
    value: AstNode


@dataclass(frozen=True)
class NumericExpression:
    left: AstNode
    operator: NumericSymbol
    right: AstNode


@dataclass(frozen=True)
class StringConcatExpression:
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class StringRepeatExpression:
    value: AstNode
    count: AstNode


@dataclass(frozen=True)
class TruthyAndExpression:
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class TruthyNotExpression:
    value: AstNode


@dataclass(frozen=True)
class TruthyOrExpression:
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class TernaryExpression:
    condition: AstNode
    true_expression: AstNode
    false_expression: AstNode


@dataclass(frozen=True)
class LocalArrayAssignment:
    name: LocalArrayName
    value: AstNode


@dataclass(frozen=True)
class LocalArrayEmptyAssignment:
    name: LocalArrayName


@dataclass(frozen=True)
class LocalArrayTransform:
    name: LocalArrayName
    operator: ListTransformSymbol
    value: AstNode


@dataclass(frozen=True)
class LocalArraySliceTransform:
    name: LocalArrayName
    indexes: list[int]
    operator: ListTransformSymbol
    value: AstNode


@dataclass(frozen=True)
class LocalArrayConditionalTransform:
    name: LocalArrayName
    operator: ListTransformSymbol
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class LocalArrayIndexedTransform:
    name: LocalArrayName
    index: int
    operator: ListTransformSymbol
    value: AstNode


@dataclass(frozen=True)
class LocalArrayIndexedBitwiseTransform:
    name: LocalArrayName
    index: int
    operator: ListIndexBitwiseTransformSymbol
    value: AstNode


@dataclass(frozen=True)
class LocalArrayIndexedAssignment:
    name: LocalArrayName
    index: int
    value: AstNode


@dataclass(frozen=True)
class LocalArrayIndexedTransformPair:
    first: (
        LocalArrayIndexedTransform | LocalArrayIndexedBitwiseTransform | LocalArrayIndexedAssignment
    )
    second: (
        LocalArrayIndexedTransform | LocalArrayIndexedBitwiseTransform | LocalArrayIndexedAssignment
    )


@dataclass(frozen=True)
class PairwiseArrayRef:
    name: LocalArrayName


@dataclass(frozen=True)
class PairwiseArraySubtract:
    target: PairwiseArrayRef
    source: PairwiseArrayRef


@dataclass(frozen=True)
class PairwiseArrayRange:
    name: LocalArrayName


@dataclass(frozen=True)
class ForeachLiteralValues:
    values: list[int]


@dataclass(frozen=True)
class ArrayConditionalTransformTail:
    value: AstNode
    name: LocalArrayName


@dataclass(frozen=True)
class ForeachReturnBlock:
    condition: AstNode
    value: AstNode


@dataclass(frozen=True)
class ForeachArrayName:
    name: LocalArrayName


@dataclass(frozen=True)
class ForeachArraySetBlock:
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class LocalArrayPairwiseTransform:
    target_name: LocalArrayName
    source_name: LocalArrayName
    limit_name: LocalArrayName


@dataclass(frozen=True)
class ForeachConditionalReturnStatement:
    values: list[int]
    condition: AstNode
    value: AstNode


@dataclass(frozen=True)
class LocalArrayPushWhileStatement:
    name: LocalArrayName
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class InputAssignment:
    value: AstNode


@dataclass(frozen=True)
class InputAssignmentIfStatement:
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class InputSubstitutionStatement:
    pattern: str
    replacement: str
    global_substitution: bool
    ignore_case: bool
    dot_matches_newline: bool


@dataclass(frozen=True)
class CurrentItemAssignment:
    value: AstNode


@dataclass(frozen=True)
class CurrentItemSubstitutionStatement:
    pattern: str
    replacement: str
    global_substitution: bool
    ignore_case: bool
    dot_matches_newline: bool


@dataclass(frozen=True)
class CurrentItemTransliterationStatement:
    source_chars: str
    replacement_chars: str


@dataclass(frozen=True)
class LocalScalarAssignment:
    name: LocalScalarName
    value: AstNode


@dataclass(frozen=True)
class LocalScalarAssignmentIfStatement:
    name: LocalScalarName
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class LocalScalarTarget:
    name: LocalScalarName


@dataclass(frozen=True)
class LocalScalarTargetList:
    targets: list[LocalScalarTarget]


@dataclass(frozen=True)
class ExpressionList:
    values: list[AstNode]


@dataclass(frozen=True)
class LocalScalarTupleAssignment:
    targets: list[LocalScalarTarget]
    values: list[AstNode]


@dataclass(frozen=True)
class LocalScalarTupleListAssignment:
    targets: list[LocalScalarTarget]
    value: AstNode


@dataclass(frozen=True)
class LocalScalarAppendIfStatement:
    name: LocalScalarName
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class LocalScalarNumericAssignmentIfStatement:
    name: LocalScalarName
    operator: NumericSymbol
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class LocalScalarNumericAssignmentWhileStatement:
    name: LocalScalarName
    operator: NumericSymbol
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class ToFloatValListStatement:
    pass


@dataclass(frozen=True)
class ByteOrderAssignmentStatement:
    value: AstNode


@dataclass(frozen=True)
class ByteOrderToggleStatement:
    pass


@dataclass(frozen=True)
class ByteOrderToggleIfStatement:
    condition: AstNode


@dataclass(frozen=True)
class ReturnIfStatement:
    value: AstNode
    condition: AstNode


@dataclass(frozen=True)
class ReturnUnlessStatement:
    fallback: AstNode
    condition: AstNode


@dataclass(frozen=True)
class StatementProgram:
    statements: list[ProgramStatement]
    expression: AstNode


@dataclass(frozen=True)
class CompileState:
    instructions: list[VmInstruction]
    next_register: int
    local_arrays: LocalArrayRegisters = field(default_factory=dict)
    local_scalars: LocalScalarRegisters = field(default_factory=dict)
    input_overrides: InputOverrides = field(default_factory=dict)
    current_item_register: str | None = None


@dataclass(frozen=True)
class CompiledNode:
    register: str
    state: CompileState


@dataclass(frozen=True)
class SplitSeparatorValue:
    value: str
    kind: SplitSeparatorKind


@dataclass(frozen=True)
class UnpackTemplateSpec:
    template: UnpackTemplate
    skip_bytes: int = 0
