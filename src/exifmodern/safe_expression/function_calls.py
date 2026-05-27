"""Function-call bytecode compilation for safe expressions."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from exifmodern.safe_expression import expression_compilation
from exifmodern.safe_expression.ast import (
    AstNode,
    CompiledNode,
    CompileState,
    FunctionCall,
    LocalArrayValue,
    LocalScalarReference,
    RegexLiteral,
    SafeInputName,
    SelfReference,
    SplitSeparatorValue,
    StringConcatExpression,
    StringLiteral,
    StringRepeatExpression,
    TagInfoReference,
    TagReference,
    UnpackTemplateSpec,
    ValListReference,
)
from exifmodern.safe_expression.bytecode import (
    BinaryNumericCall,
    ExifToolCallArgument,
    ExifToolFunctionCall,
    ExifToolScalarArgument,
    ExifToolVariadicArgument,
    JoinString,
    LoadConst,
    PackBinary,
    PackBinaryValue,
    PackTemplate,
    PrintSpatialFrequencyResponse,
    ReadBinaryValue,
    ReverseList,
    SpliceList,
    SplitString,
    Sprintf,
    Substr,
    UnaryNumericCall,
    UnaryScalarCall,
    UnpackBinary,
    UnpackHexGroups,
)
from exifmodern.safe_expression.compile_state import (
    append_instruction,
    int_literal_value_or_none,
    load_input_instruction,
    local_array_register,
)
from exifmodern.safe_expression.errors import SafeExpressionCompileError
from exifmodern.safe_expression.exiftool_compat import (
    ExifToolFunction,
    exiftool_signature_or_none,
)
from exifmodern.safe_expression.operators import (
    binary_numeric_function,
    binary_read_kind_or_none,
    unary_numeric_function,
    unary_scalar_function,
)

HEX_GROUP_UNPACK_RE = re.compile(r"^(?:H\d+)+$")
HEX_GROUP_RE = re.compile(r"H(\d+)")


@dataclass(frozen=True)
class CompiledArguments:
    registers: list[str]
    state: CompileState


@dataclass(frozen=True)
class CompiledExifToolArguments:
    arguments: list[ExifToolCallArgument]
    state: CompileState


def compile_function_call(
    ast: FunctionCall,
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
    compile_indexed_input_reference: Callable[
        [SafeInputName, int | None, CompileState], CompiledNode
    ],
) -> CompiledNode:
    if ast.name in {"int", "log", "exp", "sqrt"} and len(ast.arguments) == 1:
        value = compile_node(ast.arguments[0], state)
        unary_function = unary_numeric_function(ast.name)
        return append_instruction(
            value.state,
            lambda register: UnaryNumericCall(register, unary_function, value.register),
        )
    if ast.name == "atan2" and len(ast.arguments) == 2:
        left = compile_numeric_context_node(ast.arguments[0], state, compile_node)
        right = compile_numeric_context_node(ast.arguments[1], left.state, compile_node)
        binary_function = binary_numeric_function(ast.name)
        return append_instruction(
            right.state,
            lambda register: BinaryNumericCall(
                register,
                binary_function,
                left.register,
                right.register,
            ),
        )
    if ast.name == "GetByteOrder" and not ast.arguments:
        return compile_indexed_input_reference("$byte_order", None, state)
    if ast.name == "Image::ExifTool::Exif::PrintSFR" and len(ast.arguments) == 1:
        value = compile_node(ast.arguments[0], state)
        byte_order = compile_indexed_input_reference("$byte_order", None, value.state)
        return append_instruction(
            byte_order.state,
            lambda register: PrintSpatialFrequencyResponse(
                register,
                value.register,
                byte_order.register,
            ),
        )
    binary_read_kind = binary_read_kind_or_none(ast.name)
    if binary_read_kind is not None and len(ast.arguments) == 2:
        value = compile_node(ast.arguments[0], state)
        offset = compile_numeric_context_node(ast.arguments[1], value.state, compile_node)
        if binary_read_kind == "uint8":
            read_state = offset.state
            byte_order_register = None
        else:
            read_byte_order = compile_indexed_input_reference("$byte_order", None, offset.state)
            read_state = read_byte_order.state
            byte_order_register = read_byte_order.register
        return append_instruction(
            read_state,
            lambda register: ReadBinaryValue(
                register,
                value.register,
                offset.register,
                binary_read_kind,
                byte_order_register,
            ),
        )
    if (
        ast.name
        in {
            "abs",
            "length",
            "chr",
            "defined",
            "hex",
            "getgrgid",
            "getpwuid",
            "oct",
            "IsInt",
            "IsFloat",
            "lc",
            "ord",
            "ref",
            "uc",
            "ucfirst",
        }
        and len(ast.arguments) == 1
    ):
        value = compile_node(ast.arguments[0], state)
        scalar_function = unary_scalar_function(ast.name)
        return append_instruction(
            value.state,
            lambda register: UnaryScalarCall(register, scalar_function, value.register),
        )
    if ast.name == "split" and len(ast.arguments) in {2, 3}:
        separator_value = split_separator_value(ast.arguments[0])
        separator = append_instruction(
            state,
            lambda register: LoadConst(register, separator_value.value),
        )
        value = compile_node(ast.arguments[1], separator.state)
        limit = compile_node(ast.arguments[2], value.state) if len(ast.arguments) == 3 else None
        split_state = value.state if limit is None else limit.state
        limit_register = None if limit is None else limit.register
        return append_instruction(
            split_state,
            lambda register: SplitString(
                register,
                separator.register,
                value.register,
                separator_value.kind,
                limit_register,
            ),
        )
    if ast.name == "join" and len(ast.arguments) == 2:
        separator = compile_node(ast.arguments[0], state)
        value = compile_node(ast.arguments[1], separator.state)
        return append_instruction(
            value.state,
            lambda register: JoinString(register, separator.register, value.register),
        )
    if ast.name == "reverse" and len(ast.arguments) == 1:
        value = compile_node(ast.arguments[0], state)
        return append_instruction(
            value.state,
            lambda register: ReverseList(register, value.register),
        )
    if ast.name == "splice" and len(ast.arguments) == 3:
        source_argument = ast.arguments[0]
        if not isinstance(source_argument, LocalArrayValue):
            raise SafeExpressionCompileError("splice source must be a local array.")
        source = local_array_register(source_argument.name, state)
        start = compile_numeric_context_node(ast.arguments[1], state, compile_node)
        length = compile_numeric_context_node(ast.arguments[2], start.state, compile_node)
        return append_instruction(
            length.state,
            lambda register: SpliceList(register, source, start.register, length.register),
        )
    if ast.name == "substr" and len(ast.arguments) in {2, 3}:
        value = compile_node(ast.arguments[0], state)
        start = compile_node(ast.arguments[1], value.state)
        if len(ast.arguments) == 2:
            return append_instruction(
                start.state,
                lambda register: Substr(register, value.register, start.register, None),
            )
        length = compile_node(ast.arguments[2], start.state)
        return append_instruction(
            length.state,
            lambda register: Substr(register, value.register, start.register, length.register),
        )
    if ast.name == "unpack" and len(ast.arguments) == 2:
        hex_group_lengths = hex_group_unpack_lengths_or_none(ast.arguments[0])
        value = compile_node(ast.arguments[1], state)
        if hex_group_lengths is not None:
            return append_instruction(
                value.state,
                lambda register: UnpackHexGroups(register, value.register, hex_group_lengths),
            )
        unpack_template = unpack_template_value(ast.arguments[0])
        return append_instruction(
            value.state,
            lambda register: UnpackBinary(
                register,
                unpack_template.template,
                value.register,
                unpack_template.skip_bytes,
            ),
        )
    if ast.name == "Set16s" and len(ast.arguments) == 1:
        value = compile_numeric_context_node(ast.arguments[0], state, compile_node)
        byte_order = compile_indexed_input_reference("$byte_order", None, value.state)
        return append_instruction(
            byte_order.state,
            lambda register: PackBinaryValue(
                register,
                value.register,
                "int16",
                byte_order.register,
            ),
        )
    if ast.name == "pack" and len(ast.arguments) >= 2:
        pack_template = pack_template_value(ast.arguments[0])
        values = compile_call_arguments(ast.arguments[1:], state, compile_node=compile_node)
        return append_instruction(
            values.state,
            lambda register: PackBinary(register, pack_template, values.registers),
        )
    exiftool_compatibility_function = exiftool_signature_or_none(ast.name)
    if exiftool_compatibility_function is not None:
        has_variadic_argument = any(
            isinstance(argument, ValListReference) for argument in ast.arguments
        )
        arity_is_valid = (
            len(ast.arguments) <= exiftool_compatibility_function.maximum_arguments
            if has_variadic_argument
            else exiftool_compatibility_function.minimum_arguments
            <= len(ast.arguments)
            <= exiftool_compatibility_function.maximum_arguments
        )
        if not arity_is_valid:
            raise SafeExpressionCompileError(f"Unsupported function arity: {ast.name}")
        exiftool_arguments = compile_exiftool_call_arguments(
            exiftool_compatibility_function.vm_function,
            ast.arguments,
            state,
            compile_node=compile_node,
        )
        return append_instruction(
            exiftool_arguments.state,
            lambda register: ExifToolFunctionCall(
                register,
                exiftool_compatibility_function.vm_function,
                exiftool_arguments.arguments,
            ),
        )
    if ast.name != "sprintf" or len(ast.arguments) < 2:
        raise SafeExpressionCompileError(f"Unsupported function call: {ast.name}")
    template = static_string_expression_value_or_none(ast.arguments[0])
    if template is None:
        raise SafeExpressionCompileError("sprintf template must be a string literal.")
    sprintf_arguments = compile_call_arguments(ast.arguments[1:], state, compile_node=compile_node)
    return append_instruction(
        sprintf_arguments.state,
        lambda register: Sprintf(register, template, sprintf_arguments.registers),
    )


def compile_numeric_context_node(
    ast: AstNode,
    state: CompileState,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledNode:
    return expression_compilation.compile_numeric_context_node(
        ast,
        state,
        compile_node=compile_node,
    )


def split_separator_value(ast: AstNode) -> SplitSeparatorValue:
    if isinstance(ast, StringLiteral):
        return SplitSeparatorValue(value=ast.value, kind="literal")
    if isinstance(ast, RegexLiteral):
        if ast.pattern == " ":
            return SplitSeparatorValue(value=" ", kind="literal")
        return SplitSeparatorValue(value=ast.pattern, kind="regex")
    raise SafeExpressionCompileError("split separator must be a string or regex literal.")


def unpack_template_value(ast: AstNode) -> UnpackTemplateSpec:
    if not isinstance(ast, StringLiteral):
        raise SafeExpressionCompileError("unpack template must be a string literal.")
    if ast.value == "C*":
        return UnpackTemplateSpec("C*")
    if ast.value == "x20C*":
        return UnpackTemplateSpec("C*", skip_bytes=20)
    if ast.value == "H*":
        return UnpackTemplateSpec("H*")
    if ast.value == "H2H2":
        return UnpackTemplateSpec("H2H2")
    if ast.value == "N":
        return UnpackTemplateSpec("N")
    if ast.value == "NN":
        return UnpackTemplateSpec("NN")
    if ast.value == "N*":
        return UnpackTemplateSpec("N*")
    if ast.value == "V":
        return UnpackTemplateSpec("V")
    if ast.value == "V*":
        return UnpackTemplateSpec("V*")
    if ast.value == "VfVVf6c4lCCcclf4Vvv":
        return UnpackTemplateSpec("VfVVf6c4lCCcclf4Vvv")
    if ast.value == "x2nn":
        return UnpackTemplateSpec("x2nn")
    if ast.value == "x4N":
        return UnpackTemplateSpec("x4N")
    if ast.value == "x20N4xZ*":
        return UnpackTemplateSpec("x20N4xZ*")
    raise SafeExpressionCompileError(f"Unsupported unpack template: {ast.value}")


def hex_group_unpack_lengths_or_none(ast: AstNode) -> list[int] | None:
    if not isinstance(ast, StringLiteral) or HEX_GROUP_UNPACK_RE.fullmatch(ast.value) is None:
        return None
    return [int(match.group(1)) for match in HEX_GROUP_RE.finditer(ast.value)]


def pack_template_value(ast: AstNode) -> PackTemplate:
    if not isinstance(ast, StringLiteral):
        raise SafeExpressionCompileError("pack template must be a string literal.")
    if ast.value == "C*":
        return "C*"
    if ast.value == "H*":
        return "H*"
    if ast.value == "N":
        return "N"
    if ast.value == "N*":
        return "N*"
    raise SafeExpressionCompileError(f"Unsupported pack template: {ast.value}")


def static_string_expression_value_or_none(ast: AstNode) -> str | None:
    if isinstance(ast, StringLiteral):
        return ast.value
    if isinstance(ast, StringConcatExpression):
        left = static_string_expression_value_or_none(ast.left)
        right = static_string_expression_value_or_none(ast.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(ast, StringRepeatExpression):
        value = static_string_expression_value_or_none(ast.value)
        if value is None:
            return None
        count = int_literal_value_or_none(ast.count)
        if count is None:
            return None
        return value * count
    return None


def compile_exiftool_call_arguments(
    function: ExifToolFunction,
    arguments: list[AstNode],
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledExifToolArguments:
    compiled_arguments: list[ExifToolCallArgument] = []
    current_state = state
    for argument in arguments:
        if isinstance(argument, SelfReference | TagReference | TagInfoReference) or (
            isinstance(argument, LocalScalarReference)
            and exiftool_context_local_input_name(function, argument) is not None
        ):
            context_input_name = exiftool_context_argument_input_name(function, argument)
            if context_input_name is not None:
                compiled = append_instruction(
                    current_state,
                    load_input_instruction(context_input_name),
                )
            else:
                compiled = append_instruction(
                    current_state,
                    lambda register: LoadConst(register, None),
                )
            compiled_arguments.append(ExifToolScalarArgument(compiled.register))
        elif isinstance(argument, ValListReference):
            compiled = compile_node(argument, current_state)
            compiled_arguments.append(ExifToolVariadicArgument(compiled.register))
        else:
            compiled = compile_node(argument, current_state)
            compiled_arguments.append(ExifToolScalarArgument(compiled.register))
        current_state = compiled.state
    return CompiledExifToolArguments(arguments=compiled_arguments, state=current_state)


def exiftool_context_argument_input_name(
    function: ExifToolFunction,
    argument: SelfReference | TagReference | TagInfoReference | LocalScalarReference,
) -> str | None:
    if function in (
        "calc_scale_factor_35efl",
        "decode_cfa_pattern",
        "flir_get_image_type",
        "jpeg2000_process_jxl_codestream",
        "quicktime_calc_rotation",
        "quicktime_calc_sample_rate",
        "riff_calc_duration",
    ) and isinstance(argument, SelfReference):
        return "$self"
    if function == "samsung_crypt":
        if isinstance(argument, SelfReference):
            return "$self"
        if isinstance(argument, TagInfoReference):
            return "$tagInfo"
        if isinstance(argument, LocalScalarReference):
            return exiftool_context_local_input_name(function, argument)
    if function == "gopro_add_units":
        if isinstance(argument, SelfReference):
            return "$self"
        if isinstance(argument, TagReference):
            return "$tag"
    return None


def exiftool_context_local_input_name(
    function: ExifToolFunction,
    argument: LocalScalarReference,
) -> str | None:
    if function == "samsung_crypt" and argument.name == "tagInfo":
        return "$tagInfo"
    return None


def compile_call_arguments(
    arguments: list[AstNode],
    state: CompileState,
    *,
    compile_node: Callable[[AstNode, CompileState], CompiledNode],
) -> CompiledArguments:
    registers: list[str] = []
    current_state = state
    for argument in arguments:
        compiled = compile_node(argument, current_state)
        registers.append(compiled.register)
        current_state = compiled.state
    return CompiledArguments(registers=registers, state=current_state)
