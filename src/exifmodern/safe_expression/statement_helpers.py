"""Statement AST helper primitives for the safe-expression transformer."""

from __future__ import annotations

from exifmodern.safe_expression.ast import (
    AstNode,
    ByteOrderAssignmentStatement,
    ByteOrderToggleIfStatement,
    ByteOrderToggleStatement,
    CurrentItemAssignment,
    CurrentItemReference,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    ForeachConditionalReturnStatement,
    FunctionCall,
    FunctionCallStatement,
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
    LocalArraySliceTransform,
    LocalArrayTransform,
    LocalScalarAppendIfStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarName,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    LocalScalarReference,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    NoOpStatement,
    NumericExpression,
    NumericSymbol,
    PackageScalarAssignment,
    PackageScalarAssignmentIfStatement,
    ProgramStatement,
    RequiredModule,
    ReturnIfStatement,
    ReturnUnlessStatement,
    SelfContextAssignment,
    SelfContextAssignmentIfStatement,
    StatementProgram,
    ToFloatValListStatement,
    ValListReference,
    ValReference,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.exiftool_compat import (
    exiftool_function_has_effects,
    exiftool_signature_or_none,
)

type StatementTransformChild = ProgramStatement | AstNode

_STATEMENT_PROGRAM_STATEMENT_TYPES = (
    LocalArrayAssignment,
    LocalArrayEmptyAssignment,
    LocalArrayTransform,
    LocalArraySliceTransform,
    LocalArrayConditionalTransform,
    LocalArrayIndexedTransform,
    LocalArrayIndexedBitwiseTransform,
    LocalArrayIndexedAssignment,
    LocalArrayIndexedTransformPair,
    LocalArrayPairwiseTransform,
    ForeachConditionalReturnStatement,
    LocalArrayPushWhileStatement,
    InputAssignment,
    InputAssignmentIfStatement,
    InputSubstitutionStatement,
    CurrentItemAssignment,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    LocalScalarAppendIfStatement,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    ToFloatValListStatement,
    ByteOrderAssignmentStatement,
    ByteOrderToggleStatement,
    ByteOrderToggleIfStatement,
    SelfContextAssignment,
    SelfContextAssignmentIfStatement,
    PackageScalarAssignment,
    PackageScalarAssignmentIfStatement,
    FunctionCallStatement,
    NoOpStatement,
    ReturnIfStatement,
    ReturnUnlessStatement,
    RequiredModule,
)

_STATEMENT_PROGRAM_TERMINAL_TYPES = (
    LocalArrayAssignment,
    LocalArrayEmptyAssignment,
    LocalArrayTransform,
    LocalArraySliceTransform,
    LocalArrayConditionalTransform,
    LocalArrayIndexedTransform,
    LocalArrayIndexedBitwiseTransform,
    LocalArrayIndexedAssignment,
    LocalArrayIndexedTransformPair,
    LocalArrayPairwiseTransform,
    ForeachConditionalReturnStatement,
    LocalArrayPushWhileStatement,
    InputAssignment,
    InputAssignmentIfStatement,
    InputSubstitutionStatement,
    CurrentItemAssignment,
    CurrentItemSubstitutionStatement,
    CurrentItemTransliterationStatement,
    LocalScalarAssignment,
    LocalScalarAssignmentIfStatement,
    LocalScalarTupleAssignment,
    LocalScalarTupleListAssignment,
    LocalScalarAppendIfStatement,
    LocalScalarNumericAssignmentIfStatement,
    LocalScalarNumericAssignmentWhileStatement,
    ToFloatValListStatement,
    ByteOrderAssignmentStatement,
    ByteOrderToggleStatement,
    ByteOrderToggleIfStatement,
    SelfContextAssignmentIfStatement,
    PackageScalarAssignmentIfStatement,
    FunctionCallStatement,
    NoOpStatement,
    ReturnIfStatement,
    ReturnUnlessStatement,
    RequiredModule,
)


def function_statement_from_call(function: FunctionCall) -> ProgramStatement:
    if (
        function.name == "ToFloat"
        and len(function.arguments) == 1
        and isinstance(function.arguments[0], ValListReference)
    ):
        return ToFloatValListStatement()
    if function.name == "SetByteOrder" and len(function.arguments) == 1:
        return ByteOrderAssignmentStatement(function.arguments[0])
    if function.name == "ToggleByteOrder" and not function.arguments:
        return ByteOrderToggleStatement()
    if function.name == "warn":
        return NoOpStatement("warn")
    signature = exiftool_signature_or_none(function.name)
    if signature is not None and exiftool_function_has_effects(signature.vm_function):
        return FunctionCallStatement(function)
    raise SafeExpressionCompileError(f"Unsupported statement function: {function.name}")


def function_statement_if_from_call(
    function: FunctionCall,
    condition: AstNode,
) -> ProgramStatement:
    if function.name == "ToggleByteOrder" and not function.arguments:
        return ByteOrderToggleIfStatement(condition)
    raise SafeExpressionCompileError(f"Unsupported conditional statement function: {function.name}")


def statement_program_from_children(
    children: tuple[StatementTransformChild, ...],
) -> StatementProgram:
    statements: list[ProgramStatement] = []
    for child in children[:-1]:
        if not isinstance(child, _STATEMENT_PROGRAM_STATEMENT_TYPES):
            raise SafeExpressionCompileError("Invalid statement-program statement.")
        statements.append(child)
    expression = children[-1]
    if isinstance(expression, _STATEMENT_PROGRAM_TERMINAL_TYPES):
        raise SafeExpressionCompileError("Statement program must end with an expression.")
    return StatementProgram(statements=statements, expression=expression)


def terminal_assignment_program_from_statements(
    statements: tuple[ProgramStatement, ...],
) -> StatementProgram:
    if not statements:
        raise SafeExpressionCompileError("Terminal assignment program must contain a statement.")
    prefix_statements = list(statements[:-1])
    final_statement = statements[-1]
    if isinstance(
        final_statement,
        (InputAssignment, InputAssignmentIfStatement, InputSubstitutionStatement),
    ):
        expression: AstNode = ValReference(index=None)
    elif isinstance(final_statement, LocalScalarAssignment):
        expression = LocalScalarReference(final_statement.name)
    else:
        raise SafeExpressionCompileError(
            "Terminal assignment program must end with a value-producing assignment."
        )
    return StatementProgram(statements=[*prefix_statements, final_statement], expression=expression)


def local_array_transform_expression(statement: LocalArrayTransform) -> AstNode:
    if statement.operator == "=":
        return statement.value
    if statement.operator == "/=":
        return NumericExpression(CurrentItemReference(), "/", statement.value)
    if statement.operator == "*=":
        return NumericExpression(CurrentItemReference(), "*", statement.value)
    if statement.operator == "+=":
        return NumericExpression(CurrentItemReference(), "+", statement.value)
    if statement.operator == "-=":
        return NumericExpression(CurrentItemReference(), "-", statement.value)
    raise SafeExpressionCompileError(f"Unsupported list transform operator: {statement.operator}")


def guarded_input_numeric_assignment(
    operator: NumericSymbol,
    value: AstNode,
    condition: AstNode,
) -> InputAssignmentIfStatement:
    return InputAssignmentIfStatement(
        value=input_numeric_assignment(operator, value).value,
        condition=condition,
    )


def input_numeric_assignment(operator: NumericSymbol, value: AstNode) -> InputAssignment:
    return InputAssignment(value=NumericExpression(ValReference(index=None), operator, value))


def local_scalar_numeric_assignment_if(
    name: LocalScalarName,
    operator: NumericSymbol,
    value: AstNode,
    condition: AstNode,
) -> LocalScalarNumericAssignmentIfStatement:
    return LocalScalarNumericAssignmentIfStatement(
        name=name,
        operator=operator,
        value=value,
        condition=condition,
    )


def local_scalar_numeric_assignment_while(
    name: LocalScalarName,
    operator: NumericSymbol,
    value: AstNode,
    condition: AstNode,
) -> LocalScalarNumericAssignmentWhileStatement:
    return LocalScalarNumericAssignmentWhileStatement(
        name=name,
        operator=operator,
        value=value,
        condition=condition,
    )
