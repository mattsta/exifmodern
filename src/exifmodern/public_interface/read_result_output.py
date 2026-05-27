"""Public CLI read result stdout/stderr emission helpers."""

from __future__ import annotations

import json
import sys

from exifmodern.public_api import Diagnostic, metadata_read_result_to_json_value
from exifmodern.public_api.models import MetadataReadResult
from exifmodern.public_interface.diagnostic_output import print_diagnostics
from exifmodern.public_interface.output_policy import classify_public_read_stdout_route


def emit_read_result(
    read_result: MetadataReadResult,
) -> MetadataReadResult:
    stdout_decision = classify_public_read_stdout_route(read_result)
    if stdout_decision.action == "suppress":
        return read_result

    if stdout_decision.action == "emit_binary":
        sys.stdout.buffer.write(read_result.rendered_binary)
        return read_result

    if stdout_decision.action == "emit_text":
        print(read_result.rendered_text, end="")
    else:
        print(
            json.dumps(
                metadata_read_result_to_json_value(read_result),
                indent=2,
                sort_keys=True,
            )
        )
    return read_result


def print_read_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
    *,
    quiet_count: int = 0,
    ignore_minor_errors: bool = False,
) -> None:
    remaining: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic.code == "files_failed_condition":
            if quiet_count == 0:
                print(diagnostic.message, file=sys.stderr)
            continue
        remaining.append(diagnostic)
    print_diagnostics(
        tuple(remaining),
        quiet_count=quiet_count,
        ignore_minor_errors=ignore_minor_errors,
    )


def binary_stdout_multi_binary_diagnostic(
    read_result: MetadataReadResult,
) -> Diagnostic | None:
    _ = read_result
    return None
