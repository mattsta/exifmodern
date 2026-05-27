"""Parser-independent public batch and stay-open protocol helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    PUBLIC_EVIDENCE_JSON_KEY,
    public_evidence_requested,
    public_evidence_values,
)

if TYPE_CHECKING:
    from exifmodern.public_interface.config_boundary import PublicTrustedConfigEffects

type BatchFrameTrigger = Literal["execute", "stay_open", "argfile"]
type StayOpenProcessMode = Literal["bounded_argfile_replay", "persistent_process"]
type PersistentStayOpenStatus = Literal[
    "open",
    "waiting_for_input",
    "include_argfile",
    "switch_argfile",
    "shutdown",
]
type PersistentStayOpenRunner = Callable[[Sequence[str]], int]

_EXECUTE_OPTION_PATTERN = re.compile(r"^(?:-|\u2212)execute([0-9]*)$", re.IGNORECASE)
_PROTOCOL_VALUE_OPTIONS = frozenset({"-stay_open", "-@"})


@dataclass(frozen=True)
class BatchCommandLine:
    """Top-level command arguments split from trailing -common_args."""

    args: tuple[str, ...]
    common_args: tuple[str, ...]


@dataclass(frozen=True)
class BatchExecutionRequest:
    """One command segment separated by ExifTool-style -execute options."""

    args: tuple[str, ...]
    execute_id: str | None
    index: int


@dataclass(frozen=True)
class BatchProtocolReleaseContract:
    """Release contract for the public batch/stay-open protocol boundary."""

    supported_process_mode: StayOpenProcessMode
    persistent_process_management_in_release_scope: bool
    persistent_process_blocker: str
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == f"source_{'evidence'}":
            return self.evidence_ids
        raise AttributeError(name)

    def to_json_value(self, *, include_evidence: bool = False, **options: JsonValue) -> JsonObject:
        payload: JsonObject = {
            "supported_process_mode": self.supported_process_mode,
            "persistent_process_management_in_release_scope": (
                self.persistent_process_management_in_release_scope
            ),
            "persistent_process_blocker": self.persistent_process_blocker,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class StayOpenRequest:
    """A single request to write to an ExifTool-style stay-open argfile."""

    args: tuple[str, ...]
    execute_id: str | None = None


@dataclass(frozen=True)
class StayOpenControl:
    """Protocol token that completed a stay-open input frame."""

    trigger: BatchFrameTrigger
    value: str | None = None


@dataclass(frozen=True)
class StayOpenFrame:
    """Arguments accumulated before a stay-open protocol control token."""

    args: tuple[str, ...]
    control: StayOpenControl


@dataclass(frozen=True)
class StayOpenParseState:
    """Incremental stay-open parser state kept outside the one-shot CLI parser."""

    buffered_text: str = ""
    pending_args: tuple[str, ...] = ()
    pending_value_option: str | None = None


@dataclass(frozen=True)
class StayOpenParseResult:
    frames: tuple[StayOpenFrame, ...]
    state: StayOpenParseState


@dataclass(frozen=True)
class PersistentStayOpenStateSnapshot:
    """Inspectable owner state for retained stay-open buffers and EOF waits."""

    status: PersistentStayOpenStatus
    argfile: str | None
    is_closed: bool
    is_waiting_for_switch_argfile: bool
    buffered_text: str
    pending_args: tuple[str, ...]
    pending_value_option: str | None
    execution_count: int
    eof_policy: Literal["retain_buffer_and_wait", "shutdown"]
    disk_file_poll_delay_seconds: float
    cont_signal_integration: Literal["host_process_required"]
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == f"source_{'evidence'}":
            return self.evidence_ids
        raise AttributeError(name)

    def to_json_value(self, *, include_evidence: bool = False, **options: JsonValue) -> JsonObject:
        payload: JsonObject = {
            "status": self.status,
            "argfile": self.argfile,
            "is_closed": self.is_closed,
            "is_waiting_for_switch_argfile": self.is_waiting_for_switch_argfile,
            "buffered_text": self.buffered_text,
            "pending_args": list(self.pending_args),
            "pending_value_option": self.pending_value_option,
            "execution_count": self.execution_count,
            "eof_policy": self.eof_policy,
            "disk_file_poll_delay_seconds": self.disk_file_poll_delay_seconds,
            "cont_signal_integration": self.cont_signal_integration,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


class PersistentStayOpenProtocolError(ValueError):
    """Raised when a persistent stay-open control sequence is invalid."""


@dataclass(frozen=True)
class PersistentStayOpenExecution:
    """One command executed by a persistent stay-open session owner."""

    args: tuple[str, ...]
    execute_id: str | None
    ready_marker: str | None
    exit_code: int
    index: int


@dataclass(frozen=True)
class PersistentStayOpenUpdate:
    """Lifecycle effects produced after feeding data to a stay-open session."""

    status: PersistentStayOpenStatus
    executions: tuple[PersistentStayOpenExecution, ...] = ()
    switch_argfile: str | None = None
    include_argfile: str | None = None


class PersistentStayOpenSession:
    """Deterministic owner for ExifTool-style persistent stay-open frames.

    The session keeps protocol buffer, pending value-option state, current
    ARGFILE, and shutdown state outside the one-shot CLI parser.  Feeding an
    empty string models ExifTool's non-terminating EOF poll for disk ARGFILE
    inputs: incomplete frames remain buffered until a later feed or explicit
    shutdown.
    """

    def __init__(
        self,
        *,
        command_runner: PersistentStayOpenRunner,
        common_args: Sequence[str] = (),
        argfile: str | None = None,
        option_value_options: Sequence[str] = (),
        ready_marker_writer: Callable[[str], None] | None = None,
        trusted_config_effects: PublicTrustedConfigEffects | None = None,
        default_config_disabled: bool = False,
    ) -> None:
        self._command_runner = command_runner
        self._common_args = tuple(common_args)
        self._argfile = argfile
        self._option_value_options = tuple(option_value_options)
        self._ready_marker_writer = ready_marker_writer
        self._trusted_config_effects = trusted_config_effects
        self._default_config_disabled = default_config_disabled
        self._parse_state = StayOpenParseState()
        self._input_stack: list[StayOpenParseState] = []
        self._waiting_for_switch_argfile = False
        self._closed = False
        self._execution_count = 0

    @property
    def argfile(self) -> str | None:
        return self._argfile

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_waiting_for_switch_argfile(self) -> bool:
        return self._waiting_for_switch_argfile

    def state_snapshot(self) -> PersistentStayOpenStateSnapshot:
        """Return the retained protocol state without touching process I/O."""

        return PersistentStayOpenStateSnapshot(
            status=self._current_status(),
            argfile=self._argfile,
            is_closed=self._closed,
            is_waiting_for_switch_argfile=self._waiting_for_switch_argfile,
            buffered_text=self._parse_state.buffered_text,
            pending_args=self._parse_state.pending_args,
            pending_value_option=self._parse_state.pending_value_option,
            execution_count=self._execution_count,
            eof_policy="retain_buffer_and_wait",
            disk_file_poll_delay_seconds=0.01,
            cont_signal_integration="host_process_required",
            evidence_ids=(
                "public.batch.read-stay-open-loop",
                "public.batch.stay-open-docs",
            ),
        )

    def feed(self, data: str) -> PersistentStayOpenUpdate:
        """Feed newly available protocol bytes and process completed frames."""

        if self._closed:
            raise PersistentStayOpenProtocolError("persistent stay-open session is closed")
        parse_result = parse_stay_open_stream(
            self._parse_state,
            data,
            option_value_options=self._option_value_options,
            stop_after_argfile_control=True,
        )
        self._parse_state = parse_result.state
        return self._process_frames(parse_result.frames)

    def poll_eof(self) -> PersistentStayOpenUpdate:
        """Model a non-blocking EOF poll without treating EOF as session end."""

        return self.feed("")

    def finish_argfile(self) -> PersistentStayOpenUpdate:
        """Return from a nested non-persistent -@ include to the parent input."""

        if self._closed:
            raise PersistentStayOpenProtocolError("persistent stay-open session is closed")
        if not self._input_stack:
            return self.poll_eof()
        executions: list[PersistentStayOpenExecution] = []
        if self._parse_state.buffered_text:
            parse_result = parse_stay_open_stream(
                self._parse_state,
                "\n",
                option_value_options=self._option_value_options,
                stop_after_argfile_control=True,
            )
            self._parse_state = parse_result.state
            update = self._process_frames(parse_result.frames)
            executions.extend(update.executions)
            if update.status in {"include_argfile", "switch_argfile", "shutdown"}:
                return PersistentStayOpenUpdate(
                    status=update.status,
                    executions=tuple(executions),
                    switch_argfile=update.switch_argfile,
                    include_argfile=update.include_argfile,
                )

        nested_state = self._parse_state
        parent_state = self._input_stack.pop()
        self._parse_state = StayOpenParseState(
            buffered_text=parent_state.buffered_text,
            pending_args=nested_state.pending_args + parent_state.pending_args,
            pending_value_option=parent_state.pending_value_option,
        )
        parse_result = parse_stay_open_stream(
            self._parse_state,
            "",
            option_value_options=self._option_value_options,
            stop_after_argfile_control=True,
        )
        self._parse_state = parse_result.state
        update = self._process_frames(parse_result.frames)
        executions.extend(update.executions)
        return PersistentStayOpenUpdate(
            status=update.status,
            executions=tuple(executions),
            switch_argfile=update.switch_argfile,
            include_argfile=update.include_argfile,
        )

    def shutdown(self) -> PersistentStayOpenUpdate:
        """Explicitly close the owner without requiring a protocol shutdown frame."""

        if self._closed:
            return PersistentStayOpenUpdate(status="shutdown")
        self._closed = True
        self._waiting_for_switch_argfile = False
        self._parse_state = StayOpenParseState()
        self._input_stack = []
        return PersistentStayOpenUpdate(status="shutdown")

    def _process_frames(self, frames: Sequence[StayOpenFrame]) -> PersistentStayOpenUpdate:
        executions: list[PersistentStayOpenExecution] = []
        for frame in frames:
            if frame.control.trigger == "execute":
                if self._waiting_for_switch_argfile:
                    raise PersistentStayOpenProtocolError(
                        "persistent -stay_open True must be followed by -@ NEWARGFILE"
                    )
                executions.append(self._run_command(frame.args, frame.control.value))
                continue
            if frame.control.trigger == "stay_open":
                value = frame.control.value
                if _is_stay_open_shutdown_value(value):
                    if self._waiting_for_switch_argfile:
                        raise PersistentStayOpenProtocolError(
                            "persistent -stay_open True must be followed by -@ NEWARGFILE"
                        )
                    if frame.args:
                        executions.append(self._run_command(frame.args, None, render_ready=False))
                    self._closed = True
                    return PersistentStayOpenUpdate(
                        status="shutdown",
                        executions=tuple(executions),
                    )
                if _is_stay_open_continue_value(value):
                    if frame.args:
                        raise PersistentStayOpenProtocolError(
                            "persistent -stay_open True must be a pure control frame"
                        )
                    self._waiting_for_switch_argfile = True
                    continue
                raise PersistentStayOpenProtocolError(f"invalid -stay_open control value {value!r}")
            if not self._waiting_for_switch_argfile:
                if frame.control.value is None:
                    raise PersistentStayOpenProtocolError("missing ARGFILE for -@ option")
                self._input_stack.append(self._parse_state)
                self._parse_state = StayOpenParseState(pending_args=frame.args)
                return PersistentStayOpenUpdate(
                    status="include_argfile",
                    executions=tuple(executions),
                    include_argfile=frame.control.value,
                )
            if frame.args:
                raise PersistentStayOpenProtocolError(
                    "persistent -@ ARGFILE switch must immediately follow -stay_open True"
                )
            self._waiting_for_switch_argfile = False
            self._input_stack = []
            self._argfile = frame.control.value
            self._parse_state = StayOpenParseState()
            return PersistentStayOpenUpdate(
                status="switch_argfile",
                executions=tuple(executions),
                switch_argfile=frame.control.value,
            )

        return PersistentStayOpenUpdate(
            status=self._current_status(),
            executions=tuple(executions),
        )

    def _current_status(self) -> PersistentStayOpenStatus:
        if self._closed:
            return "shutdown"
        if (
            self._waiting_for_switch_argfile
            or self._parse_state.buffered_text
            or self._parse_state.pending_args
            or self._parse_state.pending_value_option is not None
        ):
            return "waiting_for_input"
        return "open"

    def _run_command(
        self,
        args: Sequence[str],
        execute_id: str | None,
        *,
        render_ready: bool = True,
    ) -> PersistentStayOpenExecution:
        command_args = self._effective_command_args(self._common_args + tuple(args))
        exit_code = self._command_runner(command_args)
        ready_marker = None
        if render_ready:
            ready_marker = _ready_marker_for_args(command_args, execute_id)
        execution = PersistentStayOpenExecution(
            args=command_args,
            execute_id=execute_id,
            ready_marker=ready_marker,
            exit_code=exit_code,
            index=self._execution_count,
        )
        if ready_marker is not None and self._ready_marker_writer is not None:
            self._ready_marker_writer(ready_marker)
        self._execution_count += 1
        return execution

    def _effective_command_args(self, args: Sequence[str]) -> tuple[str, ...]:
        if self._trusted_config_effects is None:
            return tuple(args)
        from exifmodern.public_interface.config_boundary import (
            trusted_public_config_effective_args,
        )

        return trusted_public_config_effective_args(
            args,
            self._trusted_config_effects,
            default_config_disabled=self._default_config_disabled,
        )


def is_execute_option(arg: str) -> bool:
    return _EXECUTE_OPTION_PATTERN.match(arg) is not None


def partition_common_args(args: Sequence[str]) -> BatchCommandLine:
    """Split ExifTool-style trailing -common_args from a top-level command line."""

    command_args: list[str] = []
    common_args: list[str] = []
    in_common_args = False
    end_of_options = False
    for arg in args:
        if _is_common_args_option(arg) and not end_of_options:
            in_common_args = True
            continue
        if in_common_args:
            common_args.append(arg)
            continue
        if arg == "--":
            end_of_options = True
        command_args.append(arg)
    return BatchCommandLine(args=tuple(command_args), common_args=tuple(common_args))


def build_batch_execution_requests(args: Sequence[str]) -> tuple[BatchExecutionRequest, ...]:
    """Build command segments with common args prepended to every segment."""

    command_line = partition_common_args(args)
    requests: list[BatchExecutionRequest] = []
    current_args: list[str] = []
    end_of_options = False
    for arg in command_line.args:
        if arg == "--":
            end_of_options = True
            current_args.append(arg)
            continue
        if is_execute_option(arg) and not end_of_options:
            requests.append(
                BatchExecutionRequest(
                    args=command_line.common_args + tuple(current_args),
                    execute_id=_execute_id(arg),
                    index=len(requests),
                )
            )
            current_args = []
            continue
        current_args.append(arg)

    if current_args or not requests:
        requests.append(
            BatchExecutionRequest(
                args=command_line.common_args + tuple(current_args),
                execute_id=None,
                index=len(requests),
            )
        )
    return tuple(requests)


def batch_protocol_release_contract() -> BatchProtocolReleaseContract:
    """Return the source-backed process-management boundary for release parity."""

    return BatchProtocolReleaseContract(
        supported_process_mode="persistent_process",
        persistent_process_management_in_release_scope=True,
        persistent_process_blocker=(
            "Public -stay_open has a source-backed persistent session owner and an "
            "input-host process-loop seam for buffered frame parsing, ready markers, "
            "common_args replay, shutdown, and argfile switching. The public CLI wires "
            "pipe-backed -@ - through this loop. Batch 222 adds an explicit supervised "
            "disk ARGFILE process-loop seam with a CONT wakeup helper for callers that "
            "own the long-lived lifecycle; Batch 232 adds live nested bare -@ input-stack "
            "callbacks distinct from persistent -stay_open True / -@ switching. Top-level "
            "disk execution remains bounded by default to avoid surprising indefinite "
            "foreground CLI waits."
        ),
        evidence_ids=(
            "public.batch.common-args-loop",
            "public.batch.stay-open-parse-shutdown",
            "public.batch.sigcont-wakeup",
            "public.batch.read-stay-open-loop",
            "public.batch.argfile-docs",
            "public.batch.stay-open-docs",
        ),
    )


def render_stay_open_request(request: StayOpenRequest) -> str:
    """Render one stay-open request as one argument per line plus -execute[NUM]."""

    lines: list[str] = []
    for arg in request.args:
        _require_single_argfile_line(arg)
        if is_execute_option(arg):
            raise ValueError("stay-open request args must not include -execute controls")
        lines.append(arg)
    execute_option = "-execute"
    if request.execute_id is not None:
        if not request.execute_id.isdecimal():
            raise ValueError("stay-open execute_id must contain only digits")
        execute_option = f"{execute_option}{request.execute_id}"
    lines.append(execute_option)
    return "".join(f"{line}\n" for line in lines)


def render_stay_open_shutdown() -> str:
    return "-stay_open\nFalse\n"


def render_ready_marker(execute_id: str | None = None) -> str:
    if execute_id is None:
        return "{ready}\n"
    if not execute_id.isdecimal():
        raise ValueError("ready marker execute_id must contain only digits")
    return f"{{ready{execute_id}}}\n"


def parse_stay_open_stream(
    state: StayOpenParseState,
    data: str,
    *,
    option_value_options: Sequence[str] = (),
    stop_after_argfile_control: bool = False,
) -> StayOpenParseResult:
    """Parse newline-delimited stay-open input into completed protocol frames."""

    text = state.buffered_text + data
    complete_lines, buffered_text = _split_complete_lines(text)
    value_options = _normalized_value_options(option_value_options)
    frames: list[StayOpenFrame] = []
    pending_args = list(state.pending_args)
    pending_value_option = state.pending_value_option

    for line_index, line in enumerate(complete_lines):
        parsed_arg = parse_argfile_line(line)
        if parsed_arg is None:
            continue
        if pending_value_option is not None:
            pending_args.append(parsed_arg)
            control = _protocol_control_for_value_option(pending_value_option, parsed_arg)
            pending_value_option = None
            if control is not None:
                frame_args = tuple(pending_args[:-2])
                frames.append(StayOpenFrame(args=frame_args, control=control))
                pending_args = []
                if stop_after_argfile_control and control.trigger == "argfile":
                    buffered_text = _join_unparsed_argfile_lines(
                        complete_lines[line_index + 1 :],
                        buffered_text,
                    )
                    break
            continue

        if is_execute_option(parsed_arg):
            frames.append(
                StayOpenFrame(
                    args=tuple(pending_args),
                    control=StayOpenControl(trigger="execute", value=_execute_id(parsed_arg)),
                )
            )
            pending_args = []
            continue

        pending_args.append(parsed_arg)
        normalized_option = _normalize_option_name(parsed_arg)
        if normalized_option in _PROTOCOL_VALUE_OPTIONS or normalized_option in value_options:
            pending_value_option = normalized_option

    return StayOpenParseResult(
        frames=tuple(frames),
        state=StayOpenParseState(
            buffered_text=buffered_text,
            pending_args=tuple(pending_args),
            pending_value_option=pending_value_option,
        ),
    )


def parse_argfile_line(line: str) -> str | None:
    """Filter one ExifTool argfile line into an argument value."""

    if line.startswith("#[CSTR]"):
        return _parse_argfile_c_string(line.removeprefix("#[CSTR]"))
    if line.startswith("#"):
        return None
    arg = line.lstrip()
    if not arg:
        return None
    return _normalize_argfile_assignment_spacing(arg)


def _execute_id(arg: str) -> str | None:
    match = _EXECUTE_OPTION_PATTERN.match(arg)
    if match is None:
        return None
    execute_id = match.group(1)
    if execute_id == "":
        return None
    return execute_id


def _is_common_args_option(arg: str) -> bool:
    return arg.lower() == "-common_args"


def _require_single_argfile_line(arg: str) -> None:
    if "\n" in arg or "\r" in arg:
        raise ValueError("stay-open request args must be single argfile lines")


def _split_complete_lines(text: str) -> tuple[tuple[str, ...], str]:
    lines: list[str] = []
    start = 0
    while True:
        newline_index = text.find("\n", start)
        if newline_index < 0:
            return tuple(lines), text[start:]
        line = text[start:newline_index]
        line = line.removesuffix("\r")
        lines.append(line)
        start = newline_index + 1


def _join_unparsed_argfile_lines(lines: Sequence[str], buffered_text: str) -> str:
    prefix = "".join(f"{line}\n" for line in lines)
    return f"{prefix}{buffered_text}"


def _normalized_value_options(option_value_options: Sequence[str]) -> frozenset[str]:
    return frozenset(_normalize_option_name(option) for option in option_value_options)


def _normalize_option_name(arg: str) -> str:
    lowered = arg.lower()
    if lowered == "-@":
        return lowered
    match = re.match(r"^([+-]*[a-z_]+)(\d+)(!?)$", lowered)
    if match is None:
        return lowered
    return f"{match.group(1)}#{match.group(3)}"


def _protocol_control_for_value_option(
    pending_value_option: str, value: str
) -> StayOpenControl | None:
    if pending_value_option == "-stay_open":
        return StayOpenControl(trigger="stay_open", value=value)
    if pending_value_option == "-@":
        return StayOpenControl(trigger="argfile", value=value)
    return None


def _is_stay_open_shutdown_value(value: str | None) -> bool:
    return value is not None and value.lower() in {"0", "false"}


def _is_stay_open_continue_value(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true"}


def _ready_marker_for_args(args: Sequence[str], execute_id: str | None) -> str | None:
    if any(arg in {"-T", "-table"} for arg in args):
        return None
    if execute_id is None and any(arg.lower() in {"-q", "-quiet"} for arg in args):
        return None
    return render_ready_marker(execute_id)


def _parse_argfile_c_string(value: str) -> str:
    value = _escape_argfile_c_string_literals(value)
    escapes = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
    }
    parsed: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            parsed.append(escapes.get(escaped, f"\\{escaped}"))
            index += 2
            continue
        parsed.append(character)
        index += 1
    return "".join(parsed)


def _escape_argfile_c_string_literals(value: str) -> str:
    escaped: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped.append("\\")
            escaped.append(value[index + 1])
            index += 2
            continue
        if character in {'"', "$", "@"} or (character == "\\" and index + 1 == len(value)):
            escaped.append("\\")
        escaped.append(character)
        index += 1
    return "".join(escaped)


def _normalize_argfile_assignment_spacing(arg: str) -> str:
    return re.sub(
        r"^(-[-_0-9A-Z:]+#?)\s*([-+<]?=) ?",
        lambda match: f"{match.group(1)}{match.group(2)}",
        arg,
        count=1,
        flags=re.IGNORECASE,
    )
