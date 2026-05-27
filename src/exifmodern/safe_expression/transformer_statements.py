"""Statement-oriented Lark transformer methods for safe expressions."""

from __future__ import annotations

from lark import Token, Transformer, v_args

from exifmodern.safe_expression.ast import (
    ArrayConditionalTransformTail,
    AstNode,
    CurrentItemAssignment,
    CurrentItemReference,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    ExpressionList,
    ForeachArrayName,
    ForeachArraySetBlock,
    ForeachConditionalReturnStatement,
    ForeachLiteralValues,
    ForeachReturnBlock,
    FunctionCall,
    InputAssignment,
    InputAssignmentIfStatement,
    InputSubstitutionStatement,
    LocalArrayAssignment,
    LocalArrayConditionalTransform,
    LocalArrayEmptyAssignment,
    LocalArrayIndexedAssignment,
    LocalArrayIndexedBitwiseTransform,
    LocalArrayIndexedTransform,
    LocalArrayIndexedTransformPair,
    LocalArrayPairwiseTransform,
    LocalArrayPushWhileStatement,
    LocalArraySliceReference,
    LocalArraySliceTransform,
    LocalArrayTransform,
    LocalArrayValue,
    LocalScalarAppendIfStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    LocalScalarReference,
    LocalScalarTarget,
    LocalScalarTargetList,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    NoOpStatement,
    PairwiseArrayRange,
    PairwiseArrayRef,
    PairwiseArraySubtract,
    ProgramStatement,
    ReturnIfStatement,
    ReturnUnlessStatement,
    StatementProgram,
    StringConcatExpression,
    TransformNode,
    UndefLiteral,
    ValReference,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.literals import substitution_statement, transliteration_statement
from exifmodern.safe_expression.statement_helpers import (
    function_statement_from_call,
    function_statement_if_from_call,
    guarded_input_numeric_assignment,
    input_numeric_assignment,
    local_scalar_numeric_assignment_if,
    local_scalar_numeric_assignment_while,
    statement_program_from_children,
    terminal_assignment_program_from_statements,
)


@v_args(inline=True)
class SafeExpressionStatementTransformerMixin(Transformer[Token, TransformNode]):
    """Transformer methods that build statement-program AST nodes."""

    def local_array_value(self, name: Token) -> LocalArrayValue:
        return LocalArrayValue(name=str(name))

    def local_scalar_ref(self, name: Token) -> LocalScalarReference:
        return LocalScalarReference(name=str(name))

    def current_item_ref(self) -> CurrentItemReference:
        return CurrentItemReference()

    def local_array_assignment(
        self,
        name: Token,
        value: AstNode,
    ) -> LocalArrayAssignment:
        return LocalArrayAssignment(name=str(name), value=value)

    def local_array_empty_assignment(
        self,
        name: Token,
    ) -> LocalArrayEmptyAssignment:
        return LocalArrayEmptyAssignment(name=str(name))

    def local_array_set_transform(
        self,
        value: AstNode,
        name: Token,
    ) -> LocalArrayTransform:
        return LocalArrayTransform(name=str(name), operator="=", value=value)

    def local_array_div_transform(
        self,
        value: AstNode,
        name: Token,
    ) -> LocalArrayTransform:
        return LocalArrayTransform(name=str(name), operator="/=", value=value)

    def local_array_mul_transform(
        self,
        value: AstNode,
        name: Token,
    ) -> LocalArrayTransform:
        return LocalArrayTransform(name=str(name), operator="*=", value=value)

    def slice_div_transform(
        self,
        value: AstNode,
        target: LocalArraySliceReference,
    ) -> LocalArraySliceTransform:
        return LocalArraySliceTransform(
            name=target.name,
            indexes=target.indexes,
            operator="/=",
            value=value,
        )

    def slice_mul_transform(
        self,
        value: AstNode,
        target: LocalArraySliceReference,
    ) -> LocalArraySliceTransform:
        return LocalArraySliceTransform(
            name=target.name,
            indexes=target.indexes,
            operator="*=",
            value=value,
        )

    def array_subtract_foreach(
        self,
        value: AstNode,
        name: Token,
    ) -> ArrayConditionalTransformTail:
        return ArrayConditionalTransformTail(value=value, name=str(name))

    def array_sub_if(
        self,
        condition: AstNode,
        tail: ArrayConditionalTransformTail,
    ) -> LocalArrayConditionalTransform:
        return LocalArrayConditionalTransform(
            name=tail.name,
            operator="-=",
            value=tail.value,
            condition=condition,
        )

    def foreach_array_name(self, name: Token) -> ForeachArrayName:
        return ForeachArrayName(name=str(name))

    def current_item_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> ForeachArraySetBlock:
        return ForeachArraySetBlock(value=value, condition=condition)

    def foreach_array_set_block(
        self,
        block: ForeachArraySetBlock,
    ) -> ForeachArraySetBlock:
        return block

    def foreach_array_set(
        self,
        name: ForeachArrayName,
        block: ForeachArraySetBlock,
    ) -> LocalArrayConditionalTransform:
        return LocalArrayConditionalTransform(
            name=name.name,
            operator="=",
            value=block.value,
            condition=block.condition,
        )

    def idx_div(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedTransform:
        return LocalArrayIndexedTransform(
            name=str(name),
            index=int(str(index)),
            operator="/=",
            value=value,
        )

    def idx_mul(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedTransform:
        return LocalArrayIndexedTransform(
            name=str(name),
            index=int(str(index)),
            operator="*=",
            value=value,
        )

    def idx_add(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedTransform:
        return LocalArrayIndexedTransform(
            name=str(name),
            index=int(str(index)),
            operator="+=",
            value=value,
        )

    def idx_sub(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedTransform:
        return LocalArrayIndexedTransform(
            name=str(name),
            index=int(str(index)),
            operator="-=",
            value=value,
        )

    def idx_bit_and(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedBitwiseTransform:
        return LocalArrayIndexedBitwiseTransform(
            name=str(name),
            index=int(str(index)),
            operator="&=",
            value=value,
        )

    def idx_bit_or(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedBitwiseTransform:
        return LocalArrayIndexedBitwiseTransform(
            name=str(name),
            index=int(str(index)),
            operator="|=",
            value=value,
        )

    def idx_bit_xor(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedBitwiseTransform:
        return LocalArrayIndexedBitwiseTransform(
            name=str(name),
            index=int(str(index)),
            operator="^=",
            value=value,
        )

    def idx_set(
        self,
        name: Token,
        index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedAssignment:
        return LocalArrayIndexedAssignment(name=str(name), index=int(str(index)), value=value)

    def idx_set_chain(
        self,
        first_name: Token,
        first_index: Token,
        second_name: Token,
        second_index: Token,
        value: AstNode,
    ) -> LocalArrayIndexedTransformPair:
        if str(first_name) != str(second_name):
            raise SafeExpressionCompileError("Indexed assignment chain must use one array.")
        return LocalArrayIndexedTransformPair(
            first=LocalArrayIndexedAssignment(
                name=str(second_name),
                index=int(str(second_index)),
                value=value,
            ),
            second=LocalArrayIndexedAssignment(
                name=str(first_name),
                index=int(str(first_index)),
                value=value,
            ),
        )

    def idx_pair(
        self,
        first: LocalArrayIndexedTransform
        | LocalArrayIndexedBitwiseTransform
        | LocalArrayIndexedAssignment,
        second: LocalArrayIndexedTransform
        | LocalArrayIndexedBitwiseTransform
        | LocalArrayIndexedAssignment,
    ) -> LocalArrayIndexedTransformPair:
        return LocalArrayIndexedTransformPair(first=first, second=second)

    def pairwise_array_ref(self, name: Token) -> PairwiseArrayRef:
        return PairwiseArrayRef(name=str(name))

    def pairwise_array_subtract(
        self,
        target: PairwiseArrayRef,
        source: PairwiseArrayRef,
    ) -> PairwiseArraySubtract:
        return PairwiseArraySubtract(target=target, source=source)

    def pairwise_array_range(self, name: Token) -> PairwiseArrayRange:
        return PairwiseArrayRange(name=str(name))

    def foreach_pairwise_range(self, value: PairwiseArrayRange) -> PairwiseArrayRange:
        return value

    def pw_sub(
        self,
        subtract: PairwiseArraySubtract,
        limit: PairwiseArrayRange,
    ) -> LocalArrayPairwiseTransform:
        return LocalArrayPairwiseTransform(
            target_name=subtract.target.name,
            source_name=subtract.source.name,
            limit_name=limit.name,
        )

    def foreach_literal_values(self, *values: Token) -> ForeachLiteralValues:
        return ForeachLiteralValues(values=[int(str(value)) for value in values])

    def foreach_return_block(self, condition: AstNode, value: AstNode) -> ForeachReturnBlock:
        return ForeachReturnBlock(condition=condition, value=value)

    def foreach_return(
        self,
        values: ForeachLiteralValues,
        block: ForeachReturnBlock,
    ) -> ForeachConditionalReturnStatement:
        return ForeachConditionalReturnStatement(
            values=values.values,
            condition=block.condition,
            value=block.value,
        )

    def local_array_push_while(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalArrayPushWhileStatement:
        return LocalArrayPushWhileStatement(
            name=str(name),
            value=value,
            condition=condition,
        )

    def input_assignment(self, value: AstNode) -> InputAssignment:
        return InputAssignment(value=value)

    def input_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return InputAssignmentIfStatement(value=value, condition=condition)

    def input_assignment_and(
        self,
        condition: AstNode,
        assignment: InputAssignment,
    ) -> InputAssignmentIfStatement:
        return InputAssignmentIfStatement(value=assignment.value, condition=condition)

    def input_num_assignment_and(
        self,
        condition: AstNode,
        assignment: InputAssignment,
    ) -> InputAssignmentIfStatement:
        return InputAssignmentIfStatement(value=assignment.value, condition=condition)

    def input_add_assignment(self, value: AstNode) -> InputAssignment:
        return input_numeric_assignment("+", value)

    def input_sub_assignment(self, value: AstNode) -> InputAssignment:
        return input_numeric_assignment("-", value)

    def input_mul_assignment(self, value: AstNode) -> InputAssignment:
        return input_numeric_assignment("*", value)

    def input_div_assignment(self, value: AstNode) -> InputAssignment:
        return input_numeric_assignment("/", value)

    def input_append_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return InputAssignmentIfStatement(
            value=StringConcatExpression(ValReference(index=None), value),
            condition=condition,
        )

    def input_add_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return guarded_input_numeric_assignment("+", value, condition)

    def input_sub_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return guarded_input_numeric_assignment("-", value, condition)

    def input_mul_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return guarded_input_numeric_assignment("*", value, condition)

    def input_div_assignment_if(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> InputAssignmentIfStatement:
        return guarded_input_numeric_assignment("/", value, condition)

    def input_substitution(self, value: Token) -> InputSubstitutionStatement:
        return substitution_statement(value)

    def current_item_assignment(self, value: AstNode) -> CurrentItemAssignment:
        return CurrentItemAssignment(value=value)

    def current_item_substitution(self, value: Token) -> CurrentItemSubstitutionStatement:
        statement = substitution_statement(value)
        return CurrentItemSubstitutionStatement(
            pattern=statement.pattern,
            replacement=statement.replacement,
            global_substitution=statement.global_substitution,
            ignore_case=statement.ignore_case,
            dot_matches_newline=statement.dot_matches_newline,
        )

    def current_item_transliteration(self, value: Token) -> CurrentItemTransliterationStatement:
        return transliteration_statement(value)

    def current_item_sub_tail(
        self,
        substitution: CurrentItemSubstitutionStatement,
    ) -> CurrentItemSubstitutionStatement:
        return substitution

    def current_item_sub_pipe(
        self,
        assignment: CurrentItemAssignment,
        substitution: CurrentItemSubstitutionStatement,
    ) -> StatementProgram:
        return StatementProgram(
            statements=[assignment, substitution],
            expression=CurrentItemReference(),
        )

    def local_scalar_assignment(
        self,
        name: Token,
        value: AstNode,
    ) -> LocalScalarAssignment:
        return LocalScalarAssignment(name=str(name), value=value)

    def local_scalar_undef_assignment(self, name: Token) -> LocalScalarAssignment:
        return LocalScalarAssignment(name=str(name), value=UndefLiteral())

    def local_scalar_assignment_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarAssignmentIfStatement:
        return LocalScalarAssignmentIfStatement(
            name=str(name),
            value=value,
            condition=condition,
        )

    def tuple_scalar_target(self, name: Token) -> LocalScalarTarget:
        return LocalScalarTarget(name=str(name))

    def tuple_scalar_targets(self, *targets: LocalScalarTarget) -> LocalScalarTargetList:
        return LocalScalarTargetList(targets=list(targets))

    def tuple_expression_values(self, *values: AstNode) -> ExpressionList:
        return ExpressionList(values=list(values))

    def scalar_tuple(
        self,
        targets: LocalScalarTargetList,
        values: ExpressionList,
    ) -> LocalScalarTupleAssignment:
        return LocalScalarTupleAssignment(targets=targets.targets, values=values.values)

    def scalar_tuple_from_list(
        self,
        targets: LocalScalarTargetList,
        value: AstNode,
    ) -> LocalScalarTupleListAssignment:
        return LocalScalarTupleListAssignment(targets=targets.targets, value=value)

    def local_scalar_append_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarAppendIfStatement:
        return LocalScalarAppendIfStatement(
            name=str(name),
            value=value,
            condition=condition,
        )

    def scalar_add_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentIfStatement:
        return local_scalar_numeric_assignment_if(str(name), "+", value, condition)

    def scalar_sub_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentIfStatement:
        return local_scalar_numeric_assignment_if(str(name), "-", value, condition)

    def scalar_mul_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentIfStatement:
        return local_scalar_numeric_assignment_if(str(name), "*", value, condition)

    def scalar_div_if(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentIfStatement:
        return local_scalar_numeric_assignment_if(str(name), "/", value, condition)

    def scalar_add_while(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentWhileStatement:
        return local_scalar_numeric_assignment_while(str(name), "+", value, condition)

    def scalar_sub_while(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentWhileStatement:
        return local_scalar_numeric_assignment_while(str(name), "-", value, condition)

    def scalar_mul_while(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentWhileStatement:
        return local_scalar_numeric_assignment_while(str(name), "*", value, condition)

    def scalar_div_while(
        self,
        name: Token,
        value: AstNode,
        condition: AstNode,
    ) -> LocalScalarNumericAssignmentWhileStatement:
        return local_scalar_numeric_assignment_while(str(name), "/", value, condition)

    def function_statement(self, function: FunctionCall) -> ProgramStatement:
        return function_statement_from_call(function)

    def warn_statement(self, _message: AstNode) -> NoOpStatement:
        return NoOpStatement("warn")

    def function_statement_if(
        self,
        function: FunctionCall,
        condition: AstNode,
    ) -> ProgramStatement:
        return function_statement_if_from_call(function, condition)

    def return_if_statement(
        self,
        value: AstNode,
        condition: AstNode,
    ) -> ReturnIfStatement:
        return ReturnIfStatement(value=value, condition=condition)

    def ret_input_num_if(
        self,
        assignment: InputAssignment,
        condition: AstNode,
    ) -> ReturnIfStatement:
        return ReturnIfStatement(value=assignment.value, condition=condition)

    def warn_return_if_statement(
        self,
        warning: FunctionCall,
        value: AstNode,
        condition: AstNode,
    ) -> ReturnIfStatement:
        if warning.name != "warn":
            raise SafeExpressionCompileError("warn return guard requires warn function call.")
        return ReturnIfStatement(value=value, condition=condition)

    def return_and_statement(
        self,
        condition: AstNode,
        value: AstNode,
    ) -> ReturnIfStatement:
        return ReturnIfStatement(value=value, condition=condition)

    def return_unless_statement(
        self,
        fallback: AstNode,
        condition: AstNode,
    ) -> ReturnUnlessStatement:
        return ReturnUnlessStatement(fallback=fallback, condition=condition)

    def return_or_statement(
        self,
        condition: AstNode,
        fallback: AstNode,
    ) -> ReturnUnlessStatement:
        return ReturnUnlessStatement(fallback=fallback, condition=condition)

    def program_statement(self, statement: ProgramStatement) -> ProgramStatement:
        return statement

    def statement_program(
        self,
        *children: ProgramStatement | AstNode,
    ) -> StatementProgram:
        return statement_program_from_children(children)

    def terminal_assignment_program(self, *statements: ProgramStatement) -> StatementProgram:
        return terminal_assignment_program_from_statements(statements)
