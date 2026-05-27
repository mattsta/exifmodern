"""Runtime context state helpers for safe-expression VM effects."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.safe_expression.vm import (
    ContextUpdate,
    InputName,
    VmInputs,
    VmValue,
    context_path_input_name,
)


@dataclass(frozen=True)
class RuntimeContextEntry:
    input_name: InputName
    value: VmValue


@dataclass(frozen=True)
class RuntimeContextState:
    entries: tuple[RuntimeContextEntry, ...]

    @classmethod
    def from_inputs(cls, inputs: VmInputs) -> RuntimeContextState:
        return cls(
            entries=tuple(
                RuntimeContextEntry(input_name=input_name, value=value)
                for input_name, value in inputs.items()
            )
        )

    def to_inputs(self) -> VmInputs:
        return {entry.input_name: entry.value for entry in self.entries}

    def with_updates(self, updates: list[ContextUpdate]) -> RuntimeContextState:
        values = self.to_inputs()
        for update in updates:
            values[context_path_input_name(update.namespace, update.path)] = update.value
        return RuntimeContextState.from_inputs(values)


def apply_context_updates(inputs: VmInputs, updates: list[ContextUpdate]) -> VmInputs:
    return RuntimeContextState.from_inputs(inputs).with_updates(updates).to_inputs()
