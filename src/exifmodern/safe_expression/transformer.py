"""Lark AST transformer for safe-expression parsing."""

from __future__ import annotations

from lark import Token, v_args

from exifmodern.safe_expression.ast import (
    AstNode,
    BitwiseExpression,
    ComparisonExpression,
    CurrentItemReference,
    DynamicPrtReference,
    DynamicRuntimeContextKey,
    DynamicValReference,
    FunctionCall,
    ListLiteral,
    LocalArrayReference,
    LocalArraySliceReference,
    LocalArrayValue,
    LocalScalarContextReference,
    LocalScalarReference,
    MapExpression,
    NumberLiteral,
    NumericExpression,
    NumericUnaryExpression,
    PackageScalarAssignment,
    PackageScalarAssignmentIfStatement,
    PackageScalarReference,
    PrtReference,
    RawListReference,
    RegexLiteral,
    RegexMatchExpression,
    RequiredModule,
    RuntimeContextKey,
    RuntimeContextPath,
    ScalarDereferenceExpression,
    ScalarReferenceExpression,
    SelfContextAssignment,
    SelfContextAssignmentIfStatement,
    SelfContextReference,
    SelfReference,
    StaticRuntimeContextKey,
    StringConcatExpression,
    StringLiteral,
    StringRepeatExpression,
    SystemOsReference,
    TagInfoReference,
    TagReference,
    TernaryExpression,
    TransformNode,
    TruthyAndExpression,
    TruthyNotExpression,
    TruthyOrExpression,
    UndefLiteral,
    UnitSuffixExpression,
    ValInterpolatedString,
    ValListReference,
    ValReference,
)
from exifmodern.safe_expression.diagnostics import INVALID_EXPRESSION_ROOT_TYPES
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.literals import (
    number_literal,
    qw_list_values,
    regex_pattern_literal,
    string_ast_literal,
)
from exifmodern.safe_expression.transformer_statements import (
    SafeExpressionStatementTransformerMixin,
)


@v_args(inline=True)
class SafeExpressionAstTransformer(
    SafeExpressionStatementTransformerMixin,
):
    def start_expr(self, *children: TransformNode) -> AstNode:
        expression = children[-1]
        if isinstance(expression, INVALID_EXPRESSION_ROOT_TYPES):
            raise SafeExpressionCompileError("Require prefix must be followed by an expression.")
        return expression

    def require_stmt(self, module: Token) -> RequiredModule:
        return RequiredModule(name=str(module))

    def return_expr(self, expression: AstNode) -> AstNode:
        return expression

    def number(self, value: Token) -> NumberLiteral:
        return NumberLiteral(number_literal(value))

    def hex_number(self, value: Token) -> NumberLiteral:
        return NumberLiteral(int(str(value), 16))

    def oct_number(self, value: Token) -> NumberLiteral:
        return NumberLiteral(int(str(value), 8))

    def string(self, value: Token) -> StringLiteral | ValInterpolatedString:
        return string_ast_literal(value)

    def regex_string(self, value: Token) -> RegexLiteral:
        return regex_pattern_literal(value)

    def qw_list(self, value: Token) -> ListLiteral:
        return ListLiteral(qw_list_values(value))

    def undef(self) -> UndefLiteral:
        return UndefLiteral()

    def val_ref(self, index: AstNode | None = None) -> ValReference | DynamicValReference:
        if index is None:
            return ValReference(index=None)
        if isinstance(index, NumberLiteral) and isinstance(index.value, int):
            return ValReference(index=index.value)
        return DynamicValReference(index=index)

    def val_unit_suffix(
        self,
        value: ValReference | DynamicValReference,
        suffix: Token,
    ) -> UnitSuffixExpression:
        return UnitSuffixExpression(value=value, suffix=str(suffix))

    def val_list_ref(self) -> ValListReference:
        return ValListReference()

    def raw_list_ref(self) -> RawListReference:
        return RawListReference()

    def scalar_ref(
        self,
        value: (
            ValReference
            | ValListReference
            | LocalScalarReference
            | LocalArrayValue
            | SelfContextReference
            | PackageScalarReference
        ),
    ) -> ScalarReferenceExpression:
        return ScalarReferenceExpression(value=value)

    def local_array_ref_value(self, name: Token) -> LocalArrayValue:
        return LocalArrayValue(name=str(name))

    def scalar_deref(
        self,
        name: Token,
        path: RuntimeContextPath | None = None,
    ) -> ScalarDereferenceExpression | LocalScalarContextReference:
        local_name = str(name)
        if path is not None:
            return LocalScalarContextReference(name=local_name, path=path)
        value: ValReference | LocalScalarReference
        if local_name == "val":
            value = ValReference(index=None)
        else:
            value = LocalScalarReference(local_name)
        return ScalarDereferenceExpression(value=value)

    def braced_scalar_deref(
        self,
        value: ValReference | DynamicValReference | LocalScalarReference,
    ) -> ScalarDereferenceExpression:
        return ScalarDereferenceExpression(value=value)

    def prt_ref(self, index: AstNode | None = None) -> PrtReference | DynamicPrtReference:
        if index is None:
            return PrtReference(index=None)
        if isinstance(index, NumberLiteral) and isinstance(index.value, int):
            return PrtReference(index=index.value)
        return DynamicPrtReference(index=index)

    def self_ref(self) -> SelfReference:
        return SelfReference()

    def tag_info_ref(self) -> TagInfoReference:
        return TagInfoReference()

    def static_context_key(self, key: Token) -> StaticRuntimeContextKey:
        return StaticRuntimeContextKey(value=str(key))

    def dynamic_context_key(self, key: AstNode) -> DynamicRuntimeContextKey:
        return DynamicRuntimeContextKey(value=key)

    def context_key_path(self, *keys: RuntimeContextKey) -> RuntimeContextPath:
        return RuntimeContextPath(keys=list(keys))

    def self_context_ref(self, path: RuntimeContextPath) -> SelfContextReference:
        return SelfContextReference(path=path)

    def self_context_assignment(
        self,
        target: SelfContextReference,
        value: AstNode,
    ) -> SelfContextAssignment:
        return SelfContextAssignment(path=target.path, value=value)

    def self_method_call(
        self,
        name: Token,
        arguments: list[AstNode] | None = None,
    ) -> FunctionCall:
        return FunctionCall(name=str(name), arguments=arguments or [])

    def self_context_assignment_if(
        self,
        condition: AstNode,
        assignment: SelfContextAssignment,
    ) -> SelfContextAssignmentIfStatement:
        return SelfContextAssignmentIfStatement(condition=condition, assignment=assignment)

    def postfix_self_assign_if(
        self,
        assignment: SelfContextAssignment,
        condition: AstNode,
    ) -> SelfContextAssignmentIfStatement:
        return SelfContextAssignmentIfStatement(condition=condition, assignment=assignment)

    def package_scalar_ref(
        self,
        name: Token,
        path: RuntimeContextPath | None = None,
    ) -> PackageScalarReference:
        return PackageScalarReference(name=str(name), path=path)

    def package_scalar_assignment(
        self,
        target: PackageScalarReference,
        value: AstNode,
    ) -> PackageScalarAssignment:
        return PackageScalarAssignment(name=target.name, path=target.path, value=value)

    def pkg_scalar_assign_if(
        self,
        condition: AstNode,
        assignment: PackageScalarAssignment,
    ) -> PackageScalarAssignmentIfStatement:
        return PackageScalarAssignmentIfStatement(condition=condition, assignment=assignment)

    def postfix_pkg_assign_if(
        self,
        assignment: PackageScalarAssignment,
        condition: AstNode,
    ) -> PackageScalarAssignmentIfStatement:
        return PackageScalarAssignmentIfStatement(condition=condition, assignment=assignment)

    def system_os_ref(self) -> SystemOsReference:
        return SystemOsReference()

    def tag_ref(self) -> TagReference:
        return TagReference()

    def local_array_ref(self, name: Token, index: AstNode) -> LocalArrayReference:
        return LocalArrayReference(name=str(name), index=index)

    def local_array_slice_ref(self, name: Token, *indexes: Token) -> LocalArraySliceReference:
        return LocalArraySliceReference(
            name=str(name),
            indexes=[int(str(index)) for index in indexes],
        )

    def final_expression(
        self,
        expression: AstNode,
    ) -> AstNode:
        return expression

    def function_call(
        self,
        name: Token,
        arguments: list[AstNode] | None = None,
    ) -> FunctionCall:
        return FunctionCall(name=str(name), arguments=arguments or [])

    def map_block_call(self, expression: AstNode, source: AstNode) -> MapExpression:
        return MapExpression(expression=expression, source=source)

    def map_function_call(self, expression: FunctionCall, source: AstNode) -> MapExpression:
        return MapExpression(expression=expression, source=source)

    def map_unary_call(self, name: Token, source: AstNode) -> MapExpression:
        return MapExpression(
            expression=FunctionCall(name=str(name), arguments=[CurrentItemReference()]),
            source=source,
        )

    def eval_block(self, expression: AstNode) -> AstNode:
        return expression

    def bareword_function_call(self, name: Token, first: AstNode, *rest: AstNode) -> FunctionCall:
        return FunctionCall(name=str(name), arguments=[first, *rest])

    def arguments(self, *children: AstNode) -> list[AstNode]:
        return list(children)

    def add(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="+", right=right)

    def sub(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="-", right=right)

    def mul(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="*", right=right)

    def div(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="/", right=right)

    def mod(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="%", right=right)

    def pow(self, left: AstNode, right: AstNode) -> NumericExpression:
        return NumericExpression(left=left, operator="**", right=right)

    def neg(self, value: AstNode) -> NumericUnaryExpression:
        return NumericUnaryExpression(operator="-", value=value)

    def pos(self, value: AstNode) -> NumericUnaryExpression:
        return NumericUnaryExpression(operator="+", value=value)

    def concat(self, left: AstNode, right: AstNode) -> StringConcatExpression:
        return StringConcatExpression(left=left, right=right)

    def repeat(self, value: AstNode, count: AstNode) -> StringRepeatExpression:
        return StringRepeatExpression(value=value, count=count)

    def bit_and(self, left: AstNode, right: AstNode) -> BitwiseExpression:
        return BitwiseExpression(left=left, operator="&", right=right)

    def bit_or(self, left: AstNode, right: AstNode) -> BitwiseExpression:
        return BitwiseExpression(left=left, operator="|", right=right)

    def bit_xor(self, left: AstNode, right: AstNode) -> BitwiseExpression:
        return BitwiseExpression(left=left, operator="^", right=right)

    def shift_left(self, left: AstNode, right: AstNode) -> BitwiseExpression:
        return BitwiseExpression(left=left, operator="<<", right=right)

    def shift_right(self, left: AstNode, right: AstNode) -> BitwiseExpression:
        return BitwiseExpression(left=left, operator=">>", right=right)

    def num_eq(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="==", right=right)

    def num_ne(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="!=", right=right)

    def lt(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="<", right=right)

    def le(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="<=", right=right)

    def gt(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator=">", right=right)

    def ge(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator=">=", right=right)

    def str_eq(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="eq", right=right)

    def str_ne(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="ne", right=right)

    def str_lt(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="lt", right=right)

    def str_le(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="le", right=right)

    def str_gt(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="gt", right=right)

    def str_ge(self, left: AstNode, right: AstNode) -> ComparisonExpression:
        return ComparisonExpression(left=left, operator="ge", right=right)

    def regex_match(self, value: AstNode, regex: Token) -> RegexMatchExpression:
        return RegexMatchExpression(value=value, regex=regex_pattern_literal(regex))

    def regex_not_match(self, value: AstNode, regex: Token) -> TruthyNotExpression:
        return TruthyNotExpression(
            value=RegexMatchExpression(value=value, regex=regex_pattern_literal(regex)),
        )

    def truthy_and(self, left: AstNode, right: AstNode) -> TruthyAndExpression:
        return TruthyAndExpression(left=left, right=right)

    def truthy_not(self, value: AstNode) -> TruthyNotExpression:
        return TruthyNotExpression(value=value)

    def truthy_or(self, left: AstNode, right: AstNode) -> TruthyOrExpression:
        return TruthyOrExpression(left=left, right=right)

    def ternary_expr(
        self,
        condition: AstNode,
        true_expression: AstNode,
        false_expression: AstNode,
    ) -> TernaryExpression:
        return TernaryExpression(
            condition=condition,
            true_expression=true_expression,
            false_expression=false_expression,
        )
