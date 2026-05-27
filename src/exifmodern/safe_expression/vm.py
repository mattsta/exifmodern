"""Typed bytecode VM for portable safe-expression operations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.safe_expression.bytecode import (
    LIVE_PHOTO_INFO_TEMPLATE,
    ArrayReferenceValue,
    BinaryNumericCall,
    BinaryNumericFunction,
    BinaryReadKind,
    BinaryWriteKind,
    BitwiseBinary,
    BitwiseOperator,
    BuildList,
    Compare,
    ComparisonOperator,
    ContextPathSegment,
    ContextUpdate,
    DereferenceScalar,
    DynamicContextPathSegment,
    ExifToolCallArgument,
    ExifToolFunctionCall,
    ExifToolScalarArgument,
    ExifToolVariadicArgument,
    FoundTagUpdate,
    HashReferenceEntry,
    HashReferenceValue,
    InputName,
    InterpolateString,
    InterpolationLiteral,
    InterpolationSegment,
    InterpolationValue,
    JoinString,
    LazyTernary,
    LazyTruthyAnd,
    LazyTruthyOr,
    ListIndexBitwiseTransform,
    ListIndexNumericTransform,
    ListIndexSet,
    ListLength,
    ListPushScalar,
    LoadConst,
    LoadContextPath,
    LoadDynamicIndex,
    LoadHashPath,
    LoadIndex,
    LoadInput,
    LoadSelfContext,
    MakeScalarReference,
    MapList,
    NumericBinary,
    NumericBinaryIfTruthy,
    NumericOperator,
    NumericUnary,
    NumericUnaryOperator,
    PackBinary,
    PackBinaryValue,
    PackTemplate,
    PairwiseListNumeric,
    PairwiseListOperator,
    PrintSpatialFrequencyResponse,
    ReadBinaryValue,
    RegexMatch,
    RegexSubstitute,
    RegisterName,
    ReverseList,
    RuntimeContextNamespace,
    SafeExpressionProgram,
    SafeExpressionResult,
    ScalarReferenceScalar,
    ScalarReferenceValue,
    SelfContextKey,
    SpliceList,
    SplitSeparatorKind,
    SplitString,
    Sprintf,
    StaticContextPathSegment,
    StoreContextPath,
    StringConcat,
    StringRepeat,
    Substr,
    Ternary,
    Transliterate,
    TruthyAnd,
    TruthyNot,
    UnaryNumericCall,
    UnaryNumericFunction,
    UnaryScalarCall,
    UnaryScalarFunction,
    UnpackBinary,
    UnpackHexGroups,
    UnpackTemplate,
    VmContextUpdates,
    VmFoundTags,
    VmInputs,
    VmInstruction,
    VmRegisters,
    VmScalar,
    VmValue,
    WhileLoop,
)
from exifmodern.safe_expression.exiftool_compat import (
    ExifToolCompatibilityError,
    ExifToolEffectResult,
    ExifToolHashEntry,
    ExifToolHashReference,
    ExifToolScalarReference,
    ExifToolValue,
    evaluate_exiftool_effect_function,
    evaluate_exiftool_function,
)
from exifmodern.services.binary import ieee754_float32, ieee754_float64
from exifmodern.services.system_metadata import group_name_or_none, user_name_or_none

PRINTF_DIRECTIVE_RE = re.compile(r"%(?:%|[-+ #0]*(\*|\d+)?(?:\.(\*|\d+))?[hlL]?([diouxXeEfFgGcs]))")
FLOAT_TEXT_RE = re.compile(r"^[+-]?(?=\d|\.\d)\d*(\.\d*)?([Ee]([+-]?\d+))?$")
FLOAT_COMMA_TEXT_RE = re.compile(r"^[+-]?(?=\d|,\d)\d*(,\d*)?([Ee]([+-]?\d+))?$")
INT_TEXT_RE = re.compile(r"^[+-]?\d+$")

__all__ = [
    "LIVE_PHOTO_INFO_TEMPLATE",
    "ArrayReferenceValue",
    "BinaryNumericCall",
    "BinaryNumericFunction",
    "BinaryReadKind",
    "BinaryWriteKind",
    "BitwiseBinary",
    "BitwiseOperator",
    "BuildList",
    "Compare",
    "ComparisonOperator",
    "ContextPathSegment",
    "ContextUpdate",
    "DereferenceScalar",
    "DynamicContextPathSegment",
    "ExifToolCallArgument",
    "ExifToolFunctionCall",
    "ExifToolScalarArgument",
    "ExifToolVariadicArgument",
    "FoundTagUpdate",
    "HashReferenceEntry",
    "HashReferenceValue",
    "InputName",
    "InterpolateString",
    "InterpolationLiteral",
    "InterpolationSegment",
    "InterpolationValue",
    "JoinString",
    "LazyTernary",
    "LazyTruthyAnd",
    "LazyTruthyOr",
    "ListIndexBitwiseTransform",
    "ListIndexNumericTransform",
    "ListIndexSet",
    "ListLength",
    "ListPushScalar",
    "LoadConst",
    "LoadContextPath",
    "LoadDynamicIndex",
    "LoadHashPath",
    "LoadIndex",
    "LoadInput",
    "LoadSelfContext",
    "MakeScalarReference",
    "MapList",
    "NumericBinary",
    "NumericBinaryIfTruthy",
    "NumericOperator",
    "NumericUnary",
    "NumericUnaryOperator",
    "PackBinary",
    "PackBinaryValue",
    "PackTemplate",
    "PairwiseListNumeric",
    "PairwiseListOperator",
    "PrintSpatialFrequencyResponse",
    "ReadBinaryValue",
    "RegexMatch",
    "RegexSubstitute",
    "RegisterName",
    "ReverseList",
    "RuntimeContextNamespace",
    "SafeExpressionProgram",
    "SafeExpressionResult",
    "SafeExpressionVmError",
    "ScalarReferenceScalar",
    "ScalarReferenceValue",
    "SelfContextKey",
    "SpliceList",
    "SplitSeparatorKind",
    "SplitString",
    "Sprintf",
    "StaticContextPathSegment",
    "StoreContextPath",
    "StringConcat",
    "StringRepeat",
    "Substr",
    "Ternary",
    "Transliterate",
    "TruthyAnd",
    "TruthyNot",
    "UnaryNumericCall",
    "UnaryNumericFunction",
    "UnaryScalarCall",
    "UnaryScalarFunction",
    "UnpackBinary",
    "UnpackHexGroups",
    "UnpackTemplate",
    "VmContextUpdates",
    "VmFoundTags",
    "VmInputs",
    "VmInstruction",
    "VmRegisters",
    "VmScalar",
    "VmValue",
    "WhileLoop",
    "context_path_input_name",
    "evaluate_program",
    "evaluate_program_with_effects",
    "perl_truthy",
    "self_context_input_name",
]


class SafeExpressionVmError(ValueError):
    """Raised when bytecode attempts an invalid safe-expression operation."""


def evaluate_program(program: SafeExpressionProgram, inputs: VmInputs) -> VmValue:
    return evaluate_program_with_effects(program, inputs).value


def evaluate_program_with_effects(
    program: SafeExpressionProgram,
    inputs: VmInputs,
) -> SafeExpressionResult:
    registers: VmRegisters = {}
    context_updates: VmContextUpdates = []
    found_tags: VmFoundTags = []
    for instruction in program.instructions:
        execute_instruction(instruction, inputs, registers, context_updates, found_tags)
    return SafeExpressionResult(
        value=read_register(registers, program.result),
        context_updates=context_updates,
        found_tags=found_tags,
    )


def execute_instruction(
    instruction: VmInstruction,
    inputs: VmInputs,
    registers: VmRegisters,
    context_updates: VmContextUpdates,
    found_tags: VmFoundTags,
) -> None:
    if isinstance(instruction, LoadConst):
        registers[instruction.target] = instruction.value
        return
    if isinstance(instruction, LoadInput):
        registers[instruction.target] = read_input(inputs, instruction.name)
        return
    if isinstance(instruction, LoadSelfContext):
        registers[instruction.target] = read_context_value(
            inputs,
            "$$self",
            [instruction.key],
            context_updates,
        )
        return
    if isinstance(instruction, LoadContextPath):
        registers[instruction.target] = read_context_value(
            inputs,
            instruction.namespace,
            context_path_segment_values(instruction.segments, registers),
            context_updates,
        )
        return
    if isinstance(instruction, LoadHashPath):
        registers[instruction.target] = read_hash_path_value(
            read_register(registers, instruction.source),
            context_path_segment_values(instruction.segments, registers),
        )
        return
    if isinstance(instruction, StoreContextPath):
        value = read_register(registers, instruction.value)
        path = context_path_segment_values(instruction.segments, registers)
        context_updates.append(
            ContextUpdate(
                namespace=instruction.namespace,
                path=path,
                value=value,
            )
        )
        registers[instruction.target] = value
        return
    if isinstance(instruction, LoadIndex):
        registers[instruction.target] = read_index(
            read_register(registers, instruction.source),
            instruction.index,
        )
        return
    if isinstance(instruction, LoadDynamicIndex):
        registers[instruction.target] = read_index(
            read_register(registers, instruction.source),
            int_value(read_register(registers, instruction.index)),
        )
        return
    if isinstance(instruction, BuildList):
        registers[instruction.target] = [
            scalar_register_value(registers, value) for value in instruction.values
        ]
        return
    if isinstance(instruction, RegexMatch):
        registers[instruction.target] = regex_match(
            string_value(read_register(registers, instruction.value)),
            instruction.pattern,
            instruction.ignore_case,
            instruction.dot_matches_newline,
        )
        return
    if isinstance(instruction, RegexSubstitute):
        registers[instruction.target] = regex_substitute(
            string_value(read_register(registers, instruction.value)),
            instruction.pattern,
            instruction.replacement,
            instruction.global_substitution,
            instruction.ignore_case,
            instruction.dot_matches_newline,
        )
        return
    if isinstance(instruction, Transliterate):
        registers[instruction.target] = transliterate_string(
            string_value(read_register(registers, instruction.value)),
            instruction.source_chars,
            instruction.replacement_chars,
        )
        return
    if isinstance(instruction, MakeScalarReference):
        registers[instruction.target] = make_scalar_reference(
            read_register(registers, instruction.value)
        )
        return
    if isinstance(instruction, DereferenceScalar):
        registers[instruction.target] = dereference_scalar(
            read_register(registers, instruction.value)
        )
        return
    if isinstance(instruction, NumericBinary):
        registers[instruction.target] = evaluate_numeric_binary(
            numeric_value(read_register(registers, instruction.left)),
            instruction.operator,
            numeric_value(read_register(registers, instruction.right)),
        )
        return
    if isinstance(instruction, NumericUnary):
        registers[instruction.target] = evaluate_numeric_unary(
            instruction.operator,
            numeric_value(read_register(registers, instruction.value)),
        )
        return
    if isinstance(instruction, BitwiseBinary):
        registers[instruction.target] = evaluate_bitwise_binary(
            int_value(read_register(registers, instruction.left)),
            instruction.operator,
            int_value(read_register(registers, instruction.right)),
        )
        return
    if isinstance(instruction, NumericBinaryIfTruthy):
        if not perl_truthy(read_register(registers, instruction.condition)):
            registers[instruction.target] = instruction.false_value
            return
        registers[instruction.target] = evaluate_numeric_binary(
            numeric_value(read_register(registers, instruction.left)),
            instruction.operator,
            numeric_value(read_register(registers, instruction.right)),
        )
        return
    if isinstance(instruction, Compare):
        registers[instruction.target] = evaluate_comparison(
            read_register(registers, instruction.left),
            instruction.operator,
            read_register(registers, instruction.right),
        )
        return
    if isinstance(instruction, Ternary):
        selected = (
            instruction.true_value
            if perl_truthy(read_register(registers, instruction.condition))
            else instruction.false_value
        )
        registers[instruction.target] = read_register(registers, selected)
        return
    if isinstance(instruction, LazyTernary):
        if perl_truthy(read_register(registers, instruction.condition)):
            execute_instructions(
                instruction.true_instructions,
                inputs,
                registers,
                context_updates,
                found_tags,
            )
            registers[instruction.target] = read_register(registers, instruction.true_result)
            return
        execute_instructions(
            instruction.false_instructions,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
        registers[instruction.target] = read_register(registers, instruction.false_result)
        return
    if isinstance(instruction, TruthyAnd):
        registers[instruction.target] = perl_truthy(
            read_register(registers, instruction.left)
        ) and perl_truthy(read_register(registers, instruction.right))
        return
    if isinstance(instruction, TruthyNot):
        registers[instruction.target] = not perl_truthy(read_register(registers, instruction.value))
        return
    if isinstance(instruction, LazyTruthyAnd):
        left = read_register(registers, instruction.left)
        if not perl_truthy(left):
            registers[instruction.target] = left
            return
        execute_instructions(
            instruction.right_instructions,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
        registers[instruction.target] = read_register(registers, instruction.right_result)
        return
    if isinstance(instruction, LazyTruthyOr):
        left = read_register(registers, instruction.left)
        if perl_truthy(left):
            registers[instruction.target] = left
            return
        execute_instructions(
            instruction.right_instructions,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
        registers[instruction.target] = read_register(registers, instruction.right_result)
        return
    if isinstance(instruction, StringConcat):
        registers[instruction.target] = string_value(
            read_register(registers, instruction.left)
        ) + string_value(read_register(registers, instruction.right))
        return
    if isinstance(instruction, StringRepeat):
        registers[instruction.target] = string_value(
            read_register(registers, instruction.value)
        ) * int_value(read_register(registers, instruction.count))
        return
    if isinstance(instruction, SplitString):
        registers[instruction.target] = split_string(
            string_value(read_register(registers, instruction.separator)),
            string_value(read_register(registers, instruction.value)),
            instruction.separator_kind,
            None
            if instruction.limit is None
            else int_value(read_register(registers, instruction.limit)),
        )
        return
    if isinstance(instruction, JoinString):
        registers[instruction.target] = join_string(
            string_value(read_register(registers, instruction.separator)),
            read_register(registers, instruction.value),
        )
        return
    if isinstance(instruction, ListLength):
        registers[instruction.target] = list_length(read_register(registers, instruction.value))
        return
    if isinstance(instruction, ReverseList):
        registers[instruction.target] = reverse_list(read_register(registers, instruction.value))
        return
    if isinstance(instruction, MapList):
        registers[instruction.target] = map_list(
            read_register(registers, instruction.value),
            instruction.item_register,
            instruction.item_instructions,
            instruction.item_result,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
        return
    if isinstance(instruction, SpliceList):
        spliced = splice_list(
            read_register(registers, instruction.value),
            int_value(read_register(registers, instruction.start)),
            int_value(read_register(registers, instruction.length)),
        )
        registers[instruction.target] = spliced.items
        registers[instruction.value] = spliced.remaining
        return
    if isinstance(instruction, ListPushScalar):
        registers[instruction.target] = list_push_scalar(
            read_register(registers, instruction.value),
            read_register(registers, instruction.item),
        )
        return
    if isinstance(instruction, PairwiseListNumeric):
        registers[instruction.target] = pairwise_list_numeric(
            read_register(registers, instruction.left),
            instruction.operator,
            read_register(registers, instruction.right),
        )
        return
    if isinstance(instruction, ListIndexNumericTransform):
        registers[instruction.target] = list_index_numeric_transform(
            read_register(registers, instruction.value),
            instruction.index,
            instruction.operator,
            read_register(registers, instruction.operand),
        )
        return
    if isinstance(instruction, ListIndexBitwiseTransform):
        registers[instruction.target] = list_index_bitwise_transform(
            read_register(registers, instruction.value),
            instruction.index,
            instruction.operator,
            read_register(registers, instruction.operand),
        )
        return
    if isinstance(instruction, ListIndexSet):
        registers[instruction.target] = list_index_set(
            read_register(registers, instruction.value),
            instruction.index,
            read_register(registers, instruction.item),
        )
        return
    if isinstance(instruction, Substr):
        length = (
            None
            if instruction.length is None
            else int_value(read_register(registers, instruction.length))
        )
        registers[instruction.target] = substr_string(
            string_value(read_register(registers, instruction.value)),
            int_value(read_register(registers, instruction.start)),
            length,
        )
        return
    if isinstance(instruction, UnpackBinary):
        registers[instruction.target] = unpack_binary(
            instruction.template,
            read_register(registers, instruction.value),
            instruction.skip_bytes,
        )
        return
    if isinstance(instruction, UnpackHexGroups):
        registers[instruction.target] = unpack_hex_groups(
            read_register(registers, instruction.value),
            instruction.nibble_lengths,
        )
        return
    if isinstance(instruction, PackBinary):
        registers[instruction.target] = pack_binary(
            instruction.template,
            [read_register(registers, value) for value in instruction.values],
        )
        return
    if isinstance(instruction, ReadBinaryValue):
        byte_order = (
            None
            if instruction.byte_order is None
            else exiftool_byte_order(read_register(registers, instruction.byte_order))
        )
        registers[instruction.target] = read_binary_value(
            read_register(registers, instruction.value),
            int_value(read_register(registers, instruction.offset)),
            instruction.kind,
            byte_order,
        )
        return
    if isinstance(instruction, PackBinaryValue):
        registers[instruction.target] = pack_binary_value(
            read_register(registers, instruction.value),
            instruction.kind,
            exiftool_byte_order(read_register(registers, instruction.byte_order)),
        )
        return
    if isinstance(instruction, PrintSpatialFrequencyResponse):
        registers[instruction.target] = print_spatial_frequency_response(
            read_register(registers, instruction.value),
            exiftool_byte_order(read_register(registers, instruction.byte_order)),
        )
        return
    if isinstance(instruction, Sprintf):
        registers[instruction.target] = sprintf_string(
            instruction.template,
            sprintf_values([read_register(registers, register) for register in instruction.values]),
        )
        return
    if isinstance(instruction, InterpolateString):
        registers[instruction.target] = interpolate_string(instruction.segments, registers)
        return
    if isinstance(instruction, UnaryNumericCall):
        registers[instruction.target] = evaluate_unary_numeric_call(
            instruction.function,
            numeric_value(read_register(registers, instruction.value)),
        )
        return
    if isinstance(instruction, BinaryNumericCall):
        registers[instruction.target] = evaluate_binary_numeric_call(
            instruction.function,
            numeric_value(read_register(registers, instruction.left)),
            numeric_value(read_register(registers, instruction.right)),
        )
        return
    if isinstance(instruction, UnaryScalarCall):
        registers[instruction.target] = evaluate_unary_scalar_call(
            instruction.function,
            read_register(registers, instruction.value),
        )
        return
    if isinstance(instruction, ExifToolFunctionCall):
        try:
            values = exiftool_call_values(instruction.values, registers)
            effect_result = evaluate_exiftool_effect_function(instruction.function, values)
            if effect_result is None:
                registers[instruction.target] = vm_value_from_exiftool_value(
                    evaluate_exiftool_function(
                        instruction.function,
                        values,
                    )
                )
            else:
                registers[instruction.target] = vm_value_from_exiftool_value(effect_result.value)
                append_exiftool_effects(effect_result, context_updates, found_tags)
        except ExifToolCompatibilityError as error:
            raise SafeExpressionVmError(str(error)) from error
        return
    if isinstance(instruction, WhileLoop):
        execute_while_loop(instruction, inputs, registers, context_updates, found_tags)
        return


def execute_instructions(
    instructions: list[VmInstruction],
    inputs: VmInputs,
    registers: VmRegisters,
    context_updates: VmContextUpdates,
    found_tags: VmFoundTags,
) -> None:
    for instruction in instructions:
        execute_instruction(instruction, inputs, registers, context_updates, found_tags)


def append_exiftool_effects(
    effect_result: ExifToolEffectResult,
    context_updates: VmContextUpdates,
    found_tags: VmFoundTags,
) -> None:
    for update in effect_result.context_updates:
        context_updates.append(
            ContextUpdate(
                namespace=update.namespace,
                path=list(update.path),
                value=vm_value_from_exiftool_value(update.value),
            )
        )
    for found_tag in effect_result.found_tags:
        found_tags.append(
            FoundTagUpdate(
                name=found_tag.name,
                value=vm_value_from_exiftool_value(found_tag.value),
            )
        )


def vm_value_from_exiftool_value(value: ExifToolValue) -> VmValue:
    return vm_scalar_from_exiftool_value(value)


def vm_scalar_from_exiftool_value(value: ExifToolValue) -> VmScalar:
    if isinstance(value, tuple):
        return ArrayReferenceValue([vm_scalar_from_exiftool_value(item) for item in value])
    if isinstance(value, ExifToolScalarReference):
        return ScalarReferenceValue(value.value)
    if isinstance(value, ExifToolHashReference):
        return HashReferenceValue(
            entries=tuple(
                HashReferenceEntry(entry.key, vm_scalar_from_exiftool_value(entry.value))
                for entry in value.entries
            )
        )
    return value


def read_input(inputs: VmInputs, name: InputName) -> VmValue:
    if name not in inputs:
        raise SafeExpressionVmError(f"Missing VM input: {name}")
    return inputs[name]


def read_context_value(
    inputs: VmInputs,
    namespace: RuntimeContextNamespace,
    path: list[str],
    context_updates: VmContextUpdates,
) -> VmValue:
    for update in reversed(context_updates):
        if update.namespace == namespace and update.path == path:
            return update.value
    return read_input(inputs, context_path_input_name(namespace, path))


def read_hash_path_value(value: VmValue, path: list[str]) -> VmValue:
    current_value = value
    for key in path:
        if not isinstance(current_value, HashReferenceValue):
            return None
        current_value = hash_reference_field(current_value, key)
    return current_value


def hash_reference_field(value: HashReferenceValue, key: str) -> VmValue:
    for entry in value.entries:
        if entry.key == key:
            return entry.value
    return None


def self_context_input_name(key: SelfContextKey) -> InputName:
    return f"$$self{{{key}}}"


def context_path_input_name(
    namespace: RuntimeContextNamespace,
    segments: list[str],
) -> InputName:
    return namespace + "".join(f"{{{segment}}}" for segment in segments)


def context_path_segment_values(
    segments: list[ContextPathSegment],
    registers: VmRegisters,
) -> list[str]:
    values: list[str] = []
    for segment in segments:
        if isinstance(segment, StaticContextPathSegment):
            values.append(segment.value)
        else:
            values.append(context_path_segment_value(read_register(registers, segment.register)))
    return values


def context_path_segment_value(value: VmValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return string_value(value)


def read_register(registers: VmRegisters, name: RegisterName) -> VmValue:
    if name not in registers:
        raise SafeExpressionVmError(f"Missing VM register: {name}")
    return registers[name]


def scalar_register_value(registers: VmRegisters, name: RegisterName) -> VmScalar:
    value = read_register(registers, name)
    if isinstance(value, list):
        raise SafeExpressionVmError("VM list construction item may not be a list.")
    return value


def read_index(value: VmValue, index: int) -> VmValue:
    if not isinstance(value, list):
        raise SafeExpressionVmError("Indexed VM value is not a list.")
    try:
        return value[index]
    except IndexError:
        return None


def evaluate_numeric_binary(left: float, operator: NumericOperator, right: float) -> float:
    if operator == "add":
        return left + right
    if operator == "sub":
        return left - right
    if operator == "mul":
        return left * right
    if operator == "div":
        if right == 0:
            raise SafeExpressionVmError("VM division by zero.")
        return left / right
    if operator == "mod":
        if right == 0:
            raise SafeExpressionVmError("VM modulo by zero.")
        return left % right
    if operator == "pow":
        try:
            return math.pow(left, right)
        except OverflowError as error:
            raise SafeExpressionVmError("VM exponentiation overflow.") from error
        except ValueError as error:
            raise SafeExpressionVmError("VM exponentiation domain error.") from error
    raise SafeExpressionVmError(f"Unsupported numeric operator: {operator}")


def evaluate_numeric_unary(operator: NumericUnaryOperator, value: float) -> float:
    if operator == "neg":
        return -value
    if operator == "pos":
        return value
    raise SafeExpressionVmError(f"Unsupported numeric unary operator: {operator}")


def evaluate_bitwise_binary(left: int, operator: BitwiseOperator, right: int) -> int:
    if operator == "bit_and":
        return left & right
    if operator == "bit_or":
        return left | right
    if operator == "bit_xor":
        return left ^ right
    if operator == "shift_left":
        if right < 0:
            raise SafeExpressionVmError("VM negative left shift count.")
        return left << right
    if operator == "shift_right":
        if right < 0:
            raise SafeExpressionVmError("VM negative right shift count.")
        return left >> right
    raise SafeExpressionVmError(f"Unsupported bitwise operator: {operator}")


def evaluate_unary_numeric_call(function: UnaryNumericFunction, value: float) -> int | float:
    if function == "int":
        return int(value)
    if function == "log":
        if value <= 0:
            raise SafeExpressionVmError("VM log domain error.")
        return math.log(value)
    if function == "exp":
        return math.exp(value)
    if function == "sqrt":
        if value < 0:
            raise SafeExpressionVmError("VM sqrt domain error.")
        return math.sqrt(value)


def evaluate_binary_numeric_call(
    function: BinaryNumericFunction,
    left: float,
    right: float,
) -> int | float:
    if function == "atan2":
        return math.atan2(left, right)
    raise SafeExpressionVmError(f"Unsupported binary numeric function: {function}")


def evaluate_unary_scalar_call(function: UnaryScalarFunction, value: VmValue) -> VmScalar:
    if function == "abs":
        return abs(numeric_value(value))
    if function == "length":
        return len(string_value(value))
    if function == "chr":
        codepoint = int_value(value)
        try:
            return chr(codepoint)
        except ValueError as error:
            raise SafeExpressionVmError(f"VM chr codepoint out of range: {codepoint}") from error
    if function == "defined":
        return value is not None
    if function == "hex":
        return int(string_value(value), 16)
    if function == "getgrgid":
        return group_name_or_none(int_value(value))
    if function == "getpwuid":
        return user_name_or_none(int_value(value))
    if function == "oct":
        return octal_value(value)
    if function == "is_int":
        return is_int_value(value)
    if function == "is_float":
        return is_float_value(value)
    if function == "lc":
        return string_value(value).lower()
    if function == "ord":
        text = string_value(value)
        if not text:
            return 0
        return ord(text[0])
    if function == "ref":
        return reference_kind(value)
    if function == "uc":
        return string_value(value).upper()
    if function == "ucfirst":
        text = string_value(value)
        if not text:
            return text
        return text[0].upper() + text[1:]
    raise SafeExpressionVmError(f"Unsupported unary scalar function: {function}")


def evaluate_comparison(left: VmValue, operator: ComparisonOperator, right: VmValue) -> bool:
    if operator == "num_eq":
        return numeric_value(left) == numeric_value(right)
    if operator == "num_ne":
        return numeric_value(left) != numeric_value(right)
    if operator == "lt":
        return numeric_value(left) < numeric_value(right)
    if operator == "le":
        return numeric_value(left) <= numeric_value(right)
    if operator == "gt":
        return numeric_value(left) > numeric_value(right)
    if operator == "ge":
        return numeric_value(left) >= numeric_value(right)
    if operator == "str_eq":
        return string_value(left) == string_value(right)
    if operator == "str_ne":
        return string_value(left) != string_value(right)
    if operator == "str_lt":
        return string_value(left) < string_value(right)
    if operator == "str_le":
        return string_value(left) <= string_value(right)
    if operator == "str_gt":
        return string_value(left) > string_value(right)
    if operator == "str_ge":
        return string_value(left) >= string_value(right)
    raise SafeExpressionVmError(f"Unsupported comparison operator: {operator}")


def numeric_value(value: VmValue) -> float:
    if (
        isinstance(value, bool)
        or value is None
        or isinstance(
            value,
            (list, ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue),
        )
    ):
        raise SafeExpressionVmError(f"VM value is not numeric: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    normalized = value.replace(",", ".")
    try:
        return float(normalized)
    except ValueError as error:
        raise SafeExpressionVmError(f"VM string value is not numeric: {value}") from error


def int_value(value: VmValue) -> int:
    return int(numeric_value(value))


def string_value(value: VmValue) -> str:
    if isinstance(value, list):
        raise SafeExpressionVmError("VM string value may not be a list.")
    if isinstance(value, (ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue)):
        raise SafeExpressionVmError("VM reference may not be stringified.")
    if value is None:
        return ""
    return str(value)


def interpolate_string(segments: list[InterpolationSegment], registers: VmRegisters) -> str:
    rendered = ""
    for segment in segments:
        if isinstance(segment, InterpolationLiteral):
            rendered += segment.text
        elif isinstance(segment, InterpolationValue):
            rendered += string_value(read_register(registers, segment.value))
    return rendered


def is_float_value(value: VmValue) -> bool:
    if (
        isinstance(value, bool)
        or value is None
        or isinstance(value, (list, ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue))
    ):
        return False
    if isinstance(value, (int, float)):
        return True
    return FLOAT_TEXT_RE.match(value) is not None or FLOAT_COMMA_TEXT_RE.match(value) is not None


def is_int_value(value: VmValue) -> bool:
    if (
        isinstance(value, bool)
        or value is None
        or isinstance(value, (list, ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue))
    ):
        return False
    return INT_TEXT_RE.match(str(value)) is not None


def split_string(
    separator: str,
    value: str,
    separator_kind: SplitSeparatorKind,
    limit: int | None = None,
) -> list[VmScalar]:
    maxsplit = 0 if limit is None else max(limit - 1, 0)
    if separator_kind == "regex":
        parts = re.split(separator, value, maxsplit=maxsplit)
        return split_parts(parts, drop_empty=limit is None)
    if separator == " ":
        return split_parts(value.split(maxsplit=maxsplit) if limit is not None else value.split())
    return split_parts(value.split(separator, maxsplit=maxsplit))


def split_parts(parts: list[str], drop_empty: bool = False) -> list[VmScalar]:
    if drop_empty:
        return [part for part in parts if part != ""]
    return [part for part in parts]


def join_string(separator: str, value: VmValue) -> str:
    if not isinstance(value, list):
        return string_value(value)
    return separator.join(string_value(item) for item in value)


def list_length(value: VmValue) -> int:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM list length value is not a list.")
    return len(value)


def reverse_list(value: VmValue) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM reverse value is not a list.")
    return list(reversed(value))


def map_list(
    value: VmValue,
    item_register: RegisterName,
    item_instructions: list[VmInstruction],
    item_result: RegisterName,
    inputs: VmInputs,
    registers: VmRegisters,
    context_updates: VmContextUpdates,
    found_tags: VmFoundTags,
) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM map value is not a list.")
    mapped: list[VmScalar] = []
    for item in value:
        registers[item_register] = item
        execute_instructions(item_instructions, inputs, registers, context_updates, found_tags)
        result = read_register(registers, item_result)
        if isinstance(result, list):
            raise SafeExpressionVmError("VM map item result may not be a list.")
        mapped.append(result)
    return mapped


@dataclass(frozen=True)
class SplicedList:
    items: list[VmScalar]
    remaining: list[VmScalar]


def splice_list(value: VmValue, start: int, length: int) -> SplicedList:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM splice value is not a list.")
    if start < 0 or length < 0:
        raise SafeExpressionVmError("VM splice requires non-negative start and length.")
    copied = [item for item in value]
    end = min(start + length, len(copied))
    return SplicedList(
        items=copied[start:end],
        remaining=[*copied[:start], *copied[end:]],
    )


def list_push_scalar(value: VmValue, item: VmValue) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM push target is not a list.")
    if isinstance(item, list):
        raise SafeExpressionVmError("VM scalar push item may not be a list.")
    return [*value, item]


def execute_while_loop(
    instruction: WhileLoop,
    inputs: VmInputs,
    registers: VmRegisters,
    context_updates: VmContextUpdates,
    found_tags: VmFoundTags,
) -> None:
    for _iteration in range(instruction.max_iterations):
        execute_instructions(
            instruction.condition_instructions,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
        if not perl_truthy(read_register(registers, instruction.condition_result)):
            return
        execute_instructions(
            instruction.body_instructions,
            inputs,
            registers,
            context_updates,
            found_tags,
        )
    raise SafeExpressionVmError(f"VM while loop exceeded {instruction.max_iterations} iterations.")


def pairwise_list_numeric(
    left: VmValue,
    operator: PairwiseListOperator,
    right: VmValue,
) -> list[VmScalar]:
    if not isinstance(left, list) or not isinstance(right, list):
        raise SafeExpressionVmError("VM pairwise numeric values must be lists.")
    mapped: list[VmScalar] = []
    for index, left_item in enumerate(left):
        try:
            right_item = right[index]
        except IndexError as error:
            raise SafeExpressionVmError(
                "VM pairwise numeric lists have different lengths."
            ) from error
        if operator == "sub":
            mapped.append(numeric_value(left_item) - numeric_value(right_item))
            continue
        raise SafeExpressionVmError(f"Unsupported pairwise list operator: {operator}")
    return mapped


def list_index_numeric_transform(
    value: VmValue,
    index: int,
    operator: NumericOperator,
    operand: VmValue,
) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM indexed numeric transform value is not a list.")
    transformed = [item for item in value]
    if index < 0 or index >= len(transformed):
        raise SafeExpressionVmError(f"VM indexed numeric transform index out of range: {index}.")
    transformed[index] = evaluate_numeric_binary(
        numeric_value(transformed[index]),
        operator,
        numeric_value(operand),
    )
    return transformed


def list_index_bitwise_transform(
    value: VmValue,
    index: int,
    operator: BitwiseOperator,
    operand: VmValue,
) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM indexed bitwise transform value must be a list.")
    transformed = [item for item in value]
    if index < 0 or index >= len(transformed):
        raise SafeExpressionVmError(f"VM indexed bitwise transform index out of range: {index}.")
    transformed[index] = evaluate_bitwise_binary(
        int(numeric_value(transformed[index])),
        operator,
        int(numeric_value(operand)),
    )
    return transformed


def list_index_set(value: VmValue, index: int, item: VmValue) -> list[VmScalar]:
    if not isinstance(value, list):
        raise SafeExpressionVmError("VM indexed set value must be a list.")
    if isinstance(item, list):
        raise SafeExpressionVmError("VM indexed set item must be scalar.")
    transformed = [entry for entry in value]
    if index < 0:
        raise SafeExpressionVmError(f"VM indexed set index out of range: {index}.")
    while index >= len(transformed):
        transformed.append(None)
    transformed[index] = item
    return transformed


def make_scalar_reference(value: VmValue) -> ScalarReferenceValue | ArrayReferenceValue:
    if isinstance(value, list):
        values: list[VmScalar] = list(exiftool_list_values(value))
        return ArrayReferenceValue(values)
    if isinstance(value, (ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue)):
        raise SafeExpressionVmError("VM reference value may not be referenced again.")
    return ScalarReferenceValue(value)


def dereference_scalar(value: VmValue) -> VmValue:
    if isinstance(value, list):
        raise SafeExpressionVmError("VM dereference value may not be a list.")
    if isinstance(value, ScalarReferenceValue):
        return value.value
    if isinstance(value, ArrayReferenceValue):
        return [item for item in value.values]
    if isinstance(value, HashReferenceValue):
        return value
    return value


def reference_kind(value: VmValue) -> str:
    if isinstance(value, ScalarReferenceValue):
        return "SCALAR"
    if isinstance(value, ArrayReferenceValue):
        return "ARRAY"
    if isinstance(value, HashReferenceValue):
        return "HASH"
    return ""


def regex_match(
    value: str,
    pattern: str,
    ignore_case: bool,
    dot_matches_newline: bool,
) -> bool:
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if dot_matches_newline:
        flags |= re.DOTALL
    return re.search(pattern, value, flags) is not None


def regex_substitute(
    value: str,
    pattern: str,
    replacement: str,
    global_substitution: bool,
    ignore_case: bool,
    dot_matches_newline: bool,
) -> str:
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if dot_matches_newline:
        flags |= re.DOTALL
    count = 0 if global_substitution else 1
    return re.sub(pattern, replacement, value, count=count, flags=flags)


def transliterate_string(value: str, source_chars: str, replacement_chars: str) -> str:
    if not source_chars or not replacement_chars:
        raise SafeExpressionVmError("Transliteration requires source and replacement chars.")
    table: dict[int, str] = {}
    last_replacement = replacement_chars[-1]
    for index, source_char in enumerate(source_chars):
        replacement = (
            replacement_chars[index] if index < len(replacement_chars) else last_replacement
        )
        table[ord(source_char)] = replacement
    return value.translate(table)


def substr_string(value: str, start: int, length: int | None) -> str:
    if length is None:
        return value[start:]
    end = start + length if length >= 0 else len(value) + length
    return value[start:end]


def unpack_binary(template: UnpackTemplate, value: VmValue, skip_bytes: int = 0) -> VmValue:
    data = binary_bytes(value)
    if skip_bytes < 0:
        raise SafeExpressionVmError(f"VM unpack skip must be non-negative: {skip_bytes}.")
    data = data[skip_bytes:]
    if template == "C*":
        return [byte for byte in data]
    if template == "H*":
        return "".join(f"{byte:02x}" for byte in data)
    if template == "H2H2":
        return [f"{byte:02x}" for byte in data[:2]]
    if template == "N":
        if len(data) < 4:
            raise SafeExpressionVmError("VM unpack N requires at least 4 bytes.")
        return uint32_big_endian_value(data, 0)
    if template == "NN":
        if len(data) < 8:
            raise SafeExpressionVmError("VM unpack NN requires at least 8 bytes.")
        return [uint32_big_endian_value(data, 0), uint32_big_endian_value(data, 4)]
    if template == "N*":
        return uint32_values(data, "big")
    if template == "V":
        if len(data) < 4:
            raise SafeExpressionVmError("VM unpack V requires at least 4 bytes.")
        return uint32_little_endian_value(data, 0)
    if template == "V*":
        return uint32_values(data, "little")
    if template == "VfVVf6c4lCCcclf4Vvv":
        return unpack_live_photo_info(data)
    if template == "x2nn":
        data = data[2:]
        if len(data) < 4:
            raise SafeExpressionVmError("VM unpack x2nn requires at least 6 bytes.")
        return [read_uint16(data, 0, "MM"), read_uint16(data, 2, "MM")]
    if template == "x4N":
        data = data[4:]
        if len(data) < 4:
            raise SafeExpressionVmError("VM unpack x4N requires at least 8 bytes.")
        return uint32_big_endian_value(data, 0)
    if template == "x20N4xZ*":
        data = data[20:]
        if len(data) < 17:
            raise SafeExpressionVmError("VM unpack x20N4xZ* requires at least 37 bytes.")
        text_bytes = data[17:]
        text: list[int] = []
        for byte in text_bytes:
            if byte == 0:
                break
            text.append(byte)
        return [
            uint32_big_endian_value(data, 0),
            uint32_big_endian_value(data, 4),
            uint32_big_endian_value(data, 8),
            uint32_big_endian_value(data, 12),
            "".join(chr(byte) for byte in text),
        ]
    raise SafeExpressionVmError(f"Unsupported unpack template: {template}")


def unpack_live_photo_info(data: list[int]) -> list[VmScalar]:
    unpacked: list[VmScalar] = []
    cursor = 0
    for token in LIVE_PHOTO_INFO_TEMPLATE:
        if token == "V":
            require_binary_length(data, cursor, 4)
            unpacked.append(uint32_little_endian_value(data, cursor))
            cursor += 4
        elif token == "f":
            require_binary_length(data, cursor, 4)
            unpacked.append(ieee754_float32(bytes(data[cursor : cursor + 4]), "little"))
            cursor += 4
        elif token == "c":
            require_binary_length(data, cursor, 1)
            unpacked.append(signed_int8(data[cursor]))
            cursor += 1
        elif token == "C":
            require_binary_length(data, cursor, 1)
            unpacked.append(data[cursor])
            cursor += 1
        elif token == "l":
            require_binary_length(data, cursor, 4)
            unpacked.append(signed_int32_little_endian_value(data, cursor))
            cursor += 4
        elif token == "v":
            require_binary_length(data, cursor, 2)
            unpacked.append(read_uint16(data, cursor, "II"))
            cursor += 2
    return unpacked


def unpack_hex_groups(value: VmValue, nibble_lengths: list[int]) -> list[VmScalar]:
    hex_text = "".join(f"{byte:02x}" for byte in binary_bytes(value))
    groups: list[VmScalar] = []
    offset = 0
    for nibble_length in nibble_lengths:
        if nibble_length <= 0:
            raise SafeExpressionVmError(
                f"VM hex-group unpack length must be positive: {nibble_length}."
            )
        groups.append(hex_text[offset : offset + nibble_length])
        offset += nibble_length
    return groups


def pack_binary(template: PackTemplate, values: list[VmValue]) -> VmValue:
    if template == "C*":
        return "".join(chr(int_value(value) & 0xFF) for value in flatten_pack_values(values))
    if template == "H*":
        if len(values) != 1:
            raise SafeExpressionVmError(f"VM pack H* expected 1 value, got {len(values)}.")
        return hex_text_to_binary_text(string_value(values[0]))
    if template == "N":
        if len(values) != 1:
            raise SafeExpressionVmError(f"VM pack N expected 1 value, got {len(values)}.")
        return uint32_big_endian_text(int_value(values[0]))
    if template == "N*":
        return "".join(
            uint32_big_endian_text(int_value(value)) for value in flatten_pack_values(values)
        )
    raise SafeExpressionVmError(f"Unsupported pack template: {template}")


def pack_binary_value(
    value: VmValue,
    kind: BinaryWriteKind,
    byte_order: Literal["II", "MM"],
) -> str:
    if kind == "int16":
        return int16_text(int_value(value), python_byte_order(byte_order))
    raise SafeExpressionVmError(f"Unsupported VM binary write kind: {kind}")


def read_binary_value(
    value: VmValue,
    offset: int,
    kind: BinaryReadKind,
    byte_order: Literal["II", "MM"] | None,
) -> VmScalar:
    data = binary_cursor_bytes(value)
    if offset < 0:
        raise SafeExpressionVmError("VM binary read offset must be non-negative.")
    if kind == "uint8":
        require_binary_length(data, offset, 1)
        return data[offset]
    if byte_order is None:
        raise SafeExpressionVmError(f"VM binary read {kind} requires byte-order context.")
    if kind == "int16":
        value = read_uint16(data, offset, byte_order)
        return value - 0x10000 if value & 0x8000 else value
    if kind == "uint16":
        return read_uint16(data, offset, byte_order)
    if kind == "uint32":
        return read_uint32(data, offset, byte_order)
    if kind == "float32":
        require_binary_length(data, offset, 4)
        return ieee754_float32(bytes(data[offset : offset + 4]), python_byte_order(byte_order))
    if kind == "float64":
        require_binary_length(data, offset, 8)
        return ieee754_float64(bytes(data[offset : offset + 8]), python_byte_order(byte_order))
    raise SafeExpressionVmError(f"Unsupported VM binary read kind: {kind}")


def print_spatial_frequency_response(
    value: VmValue,
    byte_order: Literal["II", "MM"],
) -> VmScalar:
    text = string_value(value)
    data = binary_bytes(text)
    if len(data) <= 4:
        return text
    column_count = read_uint16(data, 0, byte_order)
    row_count = read_uint16(data, 2, byte_order)
    columns = text[4:].split("\0", column_count)
    payload_start = len(data) - 8 * column_count * row_count
    if len(columns) != column_count + 1 or payload_start < 4:
        return text
    rendered_columns = columns[:-1]
    for column_index in range(column_count):
        rows: list[str] = []
        for row_index in range(row_count):
            offset = payload_start + 8 * (column_index + row_index * column_count)
            rows.append(rational64u_text(data, offset, byte_order))
        rendered_columns[column_index] += "=" + ",".join(rows)
    return "; ".join(rendered_columns)


def rational64u_text(
    data: list[int],
    offset: int,
    byte_order: Literal["II", "MM"],
) -> str:
    numerator = read_uint32(data, offset, byte_order)
    denominator = read_uint32(data, offset + 4, byte_order)
    if denominator == 0:
        return "inf" if numerator else "undef"
    return f"{numerator / denominator:.10g}"


def require_binary_length(data: list[int], offset: int, length: int) -> None:
    if offset + length > len(data):
        raise SafeExpressionVmError(
            f"VM binary read requires {length} bytes at offset {offset}, got {len(data)} bytes."
        )


def read_uint16(data: list[int], offset: int, byte_order: Literal["II", "MM"]) -> int:
    require_binary_length(data, offset, 2)
    if byte_order == "II":
        return data[offset] | (data[offset + 1] << 8)
    return (data[offset] << 8) | data[offset + 1]


def read_uint32(data: list[int], offset: int, byte_order: Literal["II", "MM"]) -> int:
    require_binary_length(data, offset, 4)
    if byte_order == "II":
        return uint32_little_endian_value(data, offset)
    return uint32_big_endian_value(data, offset)


def exiftool_byte_order(value: VmValue) -> Literal["II", "MM"]:
    text = string_value(value)
    if text == "II":
        return "II"
    if text == "MM":
        return "MM"
    raise SafeExpressionVmError(f"VM byte-order input must be II or MM, got {text!r}.")


def python_byte_order(value: Literal["II", "MM"]) -> Literal["little", "big"]:
    if value == "II":
        return "little"
    return "big"


def flatten_pack_values(values: list[VmValue]) -> list[VmScalar]:
    flattened: list[VmScalar] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def uint32_big_endian_text(value: int) -> str:
    if value < 0 or value > 0xFFFFFFFF:
        raise SafeExpressionVmError(f"VM pack N value out of range: {value}.")
    return "".join(chr((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def int16_text(value: int, byte_order: Literal["little", "big"]) -> str:
    if value < -0x8000 or value > 0x7FFF:
        raise SafeExpressionVmError(f"VM signed 16-bit pack value out of range: {value}.")
    unsigned_value = value + 0x10000 if value < 0 else value
    if byte_order == "little":
        return "".join(chr((unsigned_value >> shift) & 0xFF) for shift in (0, 8))
    return "".join(chr((unsigned_value >> shift) & 0xFF) for shift in (8, 0))


def hex_text_to_binary_text(value: str) -> str:
    normalized = "".join(character for character in value if not character.isspace())
    if len(normalized) % 2:
        normalized += "0"
    try:
        return "".join(
            chr(int(normalized[index : index + 2], 16)) for index in range(0, len(normalized), 2)
        )
    except ValueError as error:
        raise SafeExpressionVmError(f"VM pack H* value is not hexadecimal: {value}") from error


def octal_value(value: VmValue) -> int:
    text = string_value(value).strip()
    sign = -1 if text.startswith("-") else 1
    unsigned_text = text[1:] if sign == -1 else text
    if unsigned_text.lower().startswith("0x"):
        return sign * parsed_int(unsigned_text[2:], 16, text)
    if unsigned_text.lower().startswith("0b"):
        return sign * parsed_int(unsigned_text[2:], 2, text)
    return sign * parsed_int(unsigned_text, 8, text)


def parsed_int(value: str, base: int, original_value: str) -> int:
    try:
        return int(value, base)
    except ValueError as error:
        raise SafeExpressionVmError(f"VM oct value is invalid: {original_value!r}.") from error


def uint32_values(data: list[int], byte_order: Literal["big", "little"]) -> list[VmScalar]:
    if len(data) % 4:
        raise SafeExpressionVmError("VM unpack uint32 list requires a multiple of 4 bytes.")
    values: list[VmScalar] = []
    for offset in range(0, len(data), 4):
        if byte_order == "big":
            values.append(uint32_big_endian_value(data, offset))
        else:
            values.append(uint32_little_endian_value(data, offset))
    return values


def uint32_big_endian_value(data: list[int], offset: int) -> int:
    return (
        (data[offset] << 24) | (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3]
    )


def uint32_little_endian_value(data: list[int], offset: int) -> int:
    return (
        data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16) | (data[offset + 3] << 24)
    )


def signed_int8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def signed_int32_little_endian_value(data: list[int], offset: int) -> int:
    value = uint32_little_endian_value(data, offset)
    return value - 0x1_0000_0000 if value & 0x8000_0000 else value


def binary_bytes(value: VmValue) -> list[int]:
    text = string_value(value)
    return [ord(character) & 0xFF for character in text]


def binary_cursor_bytes(value: VmValue) -> list[int]:
    if isinstance(value, ScalarReferenceValue):
        return binary_bytes(value.value)
    return binary_bytes(value)


def sprintf_value(value: VmValue) -> VmScalar:
    if isinstance(value, list):
        raise SafeExpressionVmError("VM sprintf value may not be a list.")
    return value


def sprintf_values(values: list[VmValue]) -> list[VmScalar]:
    flattened: list[VmScalar] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def exiftool_call_values(
    arguments: list[ExifToolCallArgument],
    registers: VmRegisters,
) -> list[ExifToolValue]:
    values: list[ExifToolValue] = []
    for argument in arguments:
        value = read_register(registers, argument.value)
        if isinstance(argument, ExifToolScalarArgument):
            values.append(exiftool_argument_value(value))
        elif isinstance(argument, ExifToolVariadicArgument):
            if not isinstance(value, list):
                raise SafeExpressionVmError("VM variadic ExifTool argument is not a list.")
            values.extend(exiftool_list_values(value))
    return values


def exiftool_argument_value(value: VmValue) -> ExifToolValue:
    if isinstance(value, list):
        raise SafeExpressionVmError("VM ExifTool scalar argument may not be a list.")
    if isinstance(value, ScalarReferenceValue):
        return ExifToolScalarReference(value.value)
    if isinstance(value, ArrayReferenceValue):
        return tuple(exiftool_argument_value(item) for item in value.values)
    if isinstance(value, HashReferenceValue):
        return exiftool_hash_reference_value(value)
    return value


def exiftool_hash_reference_value(value: HashReferenceValue) -> ExifToolHashReference:
    return ExifToolHashReference(
        entries=tuple(
            ExifToolHashEntry(entry.key, exiftool_argument_value(entry.value))
            for entry in value.entries
        )
    )


def exiftool_scalar_value(value: VmValue) -> ScalarReferenceScalar:
    if isinstance(value, list):
        raise SafeExpressionVmError("VM ExifTool scalar argument may not be a list.")
    if isinstance(value, (ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue)):
        raise SafeExpressionVmError("VM reference may not be passed to ExifTool helpers.")
    return value


def exiftool_list_values(values: list[VmScalar]) -> list[ScalarReferenceScalar]:
    return [exiftool_scalar_value(value) for value in values]


def sprintf_string(template: str, values: list[VmScalar]) -> str:
    coerced_values = coerce_sprintf_values(template, values)
    if len(coerced_values) == 1:
        return template % coerced_values[0]
    return template % tuple(coerced_values)


def coerce_sprintf_values(template: str, values: list[VmScalar]) -> list[VmScalar]:
    coerced: list[VmScalar] = []
    value_index = 0
    for match in PRINTF_DIRECTIVE_RE.finditer(template):
        if match.group(0) == "%%":
            continue
        width = match.group(1)
        precision = match.group(2)
        conversion = match.group(3)
        if width == "*":
            coerced.append(coerce_sprintf_int(values[value_index]))
            value_index += 1
        if precision == "*":
            coerced.append(coerce_sprintf_int(values[value_index]))
            value_index += 1
        coerced.append(coerce_sprintf_conversion(conversion, values[value_index]))
        value_index += 1
    coerced.extend(values[value_index:])
    return coerced


def coerce_sprintf_conversion(conversion: str, value: VmScalar) -> VmScalar:
    if isinstance(value, (ScalarReferenceValue, ArrayReferenceValue)):
        raise SafeExpressionVmError("VM reference may not be formatted.")
    if conversion in {"d", "i", "o", "u", "x", "X"}:
        return coerce_sprintf_int(value)
    if conversion in {"e", "E", "f", "F", "g", "G"}:
        return coerce_sprintf_float(value)
    return value


def coerce_sprintf_int(value: VmScalar) -> int:
    return int_value(value)


def coerce_sprintf_float(value: VmScalar) -> float:
    return numeric_value(value)


def perl_truthy(value: VmValue) -> bool:
    if isinstance(value, (ScalarReferenceValue, ArrayReferenceValue, HashReferenceValue)):
        return True
    if value is None:
        return False
    if value is False:
        return False
    if value == 0:
        return False
    if value == "":
        return False
    return value != "0"
