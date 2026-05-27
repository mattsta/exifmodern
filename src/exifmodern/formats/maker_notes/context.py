"""Typed runtime context for maker-note object-state conversions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from exifmodern.json_types import JsonArray, JsonValue

if TYPE_CHECKING:
    from exifmodern.safe_expression.vm import InputName, VmInputs, VmScalar, VmValue

type MakerNoteContextNamespace = Literal["self", "value"]
type MakerNoteRuntimeBoundary = Literal["none", "object_state_context", "binary_tiff_output"]


@dataclass(frozen=True)
class MakerNoteContextValue:
    namespace: MakerNoteContextNamespace
    path: tuple[str, ...]
    value: JsonValue

    @property
    def input_name(self) -> InputName:
        from exifmodern.safe_expression.vm import context_path_input_name

        if self.namespace == "value":
            return context_path_input_name("$$self", ["VALUE", *self.path])
        return context_path_input_name("$$self", list(self.path))


@dataclass(frozen=True)
class MakerNoteRuntimeContext:
    values: tuple[MakerNoteContextValue, ...] = ()

    def with_values(
        self,
        values: tuple[MakerNoteContextValue, ...],
    ) -> MakerNoteRuntimeContext:
        return MakerNoteRuntimeContext(values=(*self.values, *values))

    def to_vm_inputs(self) -> VmInputs:
        inputs: VmInputs = {}
        for value in self.values:
            inputs[value.input_name] = json_value_to_vm_value(value.value)
        return inputs

    def self_value(self, path: tuple[str, ...]) -> JsonValue:
        return self.context_value("self", path)

    def value_value(self, path: tuple[str, ...]) -> JsonValue:
        return self.context_value("value", path)

    def self_string(self, path: tuple[str, ...]) -> str | None:
        return json_string(self.self_value(path))

    def self_int(self, path: tuple[str, ...]) -> int | None:
        return json_int(self.self_value(path))

    def value_int(self, path: tuple[str, ...]) -> int | None:
        return json_int(self.value_value(path))

    def context_value(
        self,
        namespace: MakerNoteContextNamespace,
        path: tuple[str, ...],
    ) -> JsonValue:
        for value in reversed(self.values):
            if value.namespace == namespace and value.path == path:
                return value.value
        return None


EMPTY_MAKER_NOTE_RUNTIME_CONTEXT = MakerNoteRuntimeContext()


def maker_note_self_context(path: tuple[str, ...], value: JsonValue) -> MakerNoteContextValue:
    return MakerNoteContextValue(namespace="self", path=path, value=value)


def maker_note_value_context(path: tuple[str, ...], value: JsonValue) -> MakerNoteContextValue:
    return MakerNoteContextValue(namespace="value", path=path, value=value)


def maker_note_runtime_context_to_json(context: MakerNoteRuntimeContext) -> JsonArray:
    return [
        {
            "namespace": value.namespace,
            "path": list(value.path),
            "value": value.value,
        }
        for value in context.values
    ]


def json_value_to_vm_value(value: JsonValue) -> VmValue:
    if isinstance(value, dict):
        from exifmodern.safe_expression.vm import HashReferenceEntry, HashReferenceValue

        return HashReferenceValue(
            entries=tuple(
                HashReferenceEntry(key=key, value=json_value_to_vm_scalar(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, list):
        return [json_value_to_vm_scalar(item) for item in value]
    return value


def json_value_to_vm_scalar(value: JsonValue) -> VmScalar:
    if isinstance(value, dict):
        from exifmodern.safe_expression.vm import HashReferenceEntry, HashReferenceValue

        return HashReferenceValue(
            entries=tuple(
                HashReferenceEntry(key=key, value=json_value_to_vm_scalar(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, list):
        from exifmodern.safe_expression.vm import HashReferenceEntry, HashReferenceValue

        return HashReferenceValue(
            entries=tuple(
                HashReferenceEntry(key=str(index), value=json_value_to_vm_scalar(item))
                for index, item in enumerate(value)
            )
        )
    return value


def json_string(value: JsonValue) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


def json_int(value: JsonValue) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
