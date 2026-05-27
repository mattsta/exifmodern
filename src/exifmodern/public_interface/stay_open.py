"""Public CLI stay-open driver helpers."""

from __future__ import annotations

import argparse
import codecs
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, Literal, Protocol

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    PUBLIC_EVIDENCE_JSON_KEY,
    public_evidence_requested,
    public_evidence_values,
)
from exifmodern.public_interface.batch_protocol import (
    PersistentStayOpenProtocolError,
    PersistentStayOpenSession,
    PersistentStayOpenStateSnapshot,
    PersistentStayOpenStatus,
    PersistentStayOpenUpdate,
    StayOpenFrame,
    StayOpenParseState,
    StayOpenProcessMode,
    parse_stay_open_stream,
    partition_common_args,
    render_ready_marker,
)

if TYPE_CHECKING:
    from exifmodern.public_interface.config_boundary import PublicTrustedConfigEffects

type PublicCommandRunner = Callable[[Sequence[str]], int]
type StayOpenInputStatus = Literal["data", "eof", "closed"]
type StayOpenSignalDeliveryStatus = Literal["delivered", "failed", "unsupported"]
type StayOpenSleeper = Callable[[float], None]

STAY_OPEN_READ_SIZE = 65536
STAY_OPEN_DISK_POLL_DELAY_SECONDS = 0.01


class StayOpenTextReader(Protocol):
    def read(self, size: int = -1) -> str: ...

    def close(self) -> None: ...


class StayOpenInputHost(Protocol):
    @property
    def argfile(self) -> str: ...

    def read_protocol_chunk(self) -> StayOpenInputChunk: ...

    def push_argfile(self, argfile: str) -> None: ...

    def return_from_argfile(self) -> bool: ...

    def switch_argfile(self, argfile: str) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class TopLevelStayOpenRequest:
    argfile: str
    common_args: tuple[str, ...]
    process_mode: StayOpenProcessMode


@dataclass(frozen=True)
class StayOpenInputChunk:
    status: StayOpenInputStatus
    text: str = ""


@dataclass(frozen=True)
class StayOpenDiskPollingContract:
    """Source-backed disk ARGFILE polling and wakeup contract."""

    poll_delay_seconds: float
    sigcont_wakeup_supported: bool
    top_level_disk_default: Literal["bounded_argfile_replay"]
    supervised_process_loop_available: bool
    evidence_ids: tuple[str, ...]

    def to_json_value(
        self,
        *,
        include_evidence: bool = False,
        **options: JsonValue,
    ) -> JsonObject:
        payload: JsonObject = {
            "poll_delay_seconds": self.poll_delay_seconds,
            "sigcont_wakeup_supported": self.sigcont_wakeup_supported,
            "top_level_disk_default": self.top_level_disk_default,
            "supervised_process_loop_available": self.supervised_process_loop_available,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class StayOpenWakeupSnapshot:
    """Inspectable wakeup-handler accounting for host-owned disk polling."""

    sigcont_installed: bool
    pending_wakeup: bool
    cont_signal_count: int
    completed_sleep_count: int
    interrupted_sleep_count: int
    evidence_ids: tuple[str, ...]

    def to_json_value(
        self,
        *,
        include_evidence: bool = False,
        **options: JsonValue,
    ) -> JsonObject:
        payload: JsonObject = {
            "sigcont_installed": self.sigcont_installed,
            "pending_wakeup": self.pending_wakeup,
            "cont_signal_count": self.cont_signal_count,
            "completed_sleep_count": self.completed_sleep_count,
            "interrupted_sleep_count": self.interrupted_sleep_count,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class StayOpenHostSignalDeliveryResult:
    """Result of a host-owned SIGCONT wakeup delivery attempt."""

    status: StayOpenSignalDeliveryStatus
    pid: int | None
    signal_name: Literal["SIGCONT"] = "SIGCONT"
    error_message: str | None = None
    evidence_ids: tuple[str, ...] = (
        "public.batch.sigcont-wakeup",
        "public.batch.sigcont-empty-handler",
        "public.batch.stay-open-docs",
    )

    def to_json_value(
        self,
        *,
        include_evidence: bool = False,
        **options: JsonValue,
    ) -> JsonObject:
        payload: JsonObject = {
            "status": self.status,
            "pid": self.pid,
            "signal_name": self.signal_name,
            "error_message": self.error_message,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


class StayOpenHostSignalDelivery:
    """Host-owned delivery of the documented disk ARGFILE wakeup signal."""

    def __init__(self, *, kill_process: Callable[[int, int], None] = os.kill) -> None:
        self._kill_process = kill_process

    def send_sigcont(self, pid: int | None = None) -> StayOpenHostSignalDeliveryResult:
        if not hasattr(signal, "SIGCONT"):
            return StayOpenHostSignalDeliveryResult(status="unsupported", pid=pid)
        resolved_pid = os.getpid() if pid is None else pid
        if resolved_pid <= 0:
            raise ValueError("stay-open SIGCONT delivery requires a positive process id")
        try:
            self._kill_process(resolved_pid, signal.SIGCONT)
        except OSError as exc:
            return StayOpenHostSignalDeliveryResult(
                status="failed",
                pid=resolved_pid,
                error_message=str(exc),
            )
        return StayOpenHostSignalDeliveryResult(status="delivered", pid=resolved_pid)


class StayOpenDiskPollSupervisor:
    """Waiter that mirrors ExifTool's disk EOF delay and CONT wakeup seam."""

    def __init__(self) -> None:
        self._wake_event = threading.Event()
        self._previous_sigcont_handler: (
            signal.Handlers | int | Callable[[int, FrameType | None], None] | None
        ) = None
        self._sigcont_installed = False
        self._cont_signal_count = 0
        self._completed_sleep_count = 0
        self._interrupted_sleep_count = 0

    def __enter__(self) -> StayOpenDiskPollSupervisor:
        self.install_sigcont_handler()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, traceback
        self.restore_sigcont_handler()
        return False

    @property
    def sigcont_installed(self) -> bool:
        return self._sigcont_installed

    def install_sigcont_handler(self) -> bool:
        if self._sigcont_installed:
            return True
        try:
            previous_handler = signal.getsignal(signal.SIGCONT)
            signal.signal(signal.SIGCONT, self.notify_cont_signal)
        except AttributeError, OSError, ValueError:
            return False
        self._previous_sigcont_handler = previous_handler
        self._sigcont_installed = True
        return True

    def restore_sigcont_handler(self) -> bool:
        if not self._sigcont_installed:
            return True
        previous_handler = self._previous_sigcont_handler
        self._sigcont_installed = False
        self._previous_sigcont_handler = None
        if previous_handler is None:
            return True
        try:
            signal.signal(signal.SIGCONT, previous_handler)
        except AttributeError, OSError, ValueError:
            return False
        return True

    def notify_cont_signal(self, signal_number: int, frame: FrameType | None) -> None:
        del signal_number, frame
        self._cont_signal_count += 1
        self._wake_event.set()

    def sleep(self, delay_seconds: float) -> None:
        woke_early = self._wake_event.wait(delay_seconds)
        self._completed_sleep_count += 1
        if woke_early:
            self._interrupted_sleep_count += 1
        self._wake_event.clear()

    def wakeup_snapshot(self) -> StayOpenWakeupSnapshot:
        return StayOpenWakeupSnapshot(
            sigcont_installed=self._sigcont_installed,
            pending_wakeup=self._wake_event.is_set(),
            cont_signal_count=self._cont_signal_count,
            completed_sleep_count=self._completed_sleep_count,
            interrupted_sleep_count=self._interrupted_sleep_count,
            evidence_ids=(
                "public.batch.sigcont-wakeup",
                "public.batch.sigcont-empty-handler",
                "public.batch.disk-poll-cont",
            ),
        )


def stay_open_disk_polling_contract() -> StayOpenDiskPollingContract:
    """Return the source-backed supervised disk stay-open lifecycle boundary."""

    return StayOpenDiskPollingContract(
        poll_delay_seconds=STAY_OPEN_DISK_POLL_DELAY_SECONDS,
        sigcont_wakeup_supported=hasattr(signal, "SIGCONT"),
        top_level_disk_default="bounded_argfile_replay",
        supervised_process_loop_available=True,
        evidence_ids=(
            "public.batch.sigcont-wakeup",
            "public.batch.read-stay-open-loop",
            "public.batch.stay-open-docs",
        ),
    )


def top_level_stay_open_argfile(args: Sequence[str]) -> str | None:
    request = top_level_stay_open_request(args)
    if request is None:
        return None
    return request.argfile


def top_level_stay_open_request(args: Sequence[str]) -> TopLevelStayOpenRequest | None:
    if not args or is_public_subcommand_name(args[0]):
        return None
    command_line = partition_common_args(args)
    command_args = command_line.args
    index = 0
    while index < len(command_args):
        arg = command_args[index]
        if arg.lower() != "-stay_open":
            index += 1
            continue
        flag_index = index + 1
        if flag_index >= len(command_args):
            raise argparse.ArgumentTypeError("Expecting argument for -stay_open option")
        flag = command_args[flag_index].lower()
        if flag in {"0", "false"}:
            return None
        if flag not in {"1", "true"}:
            return None
        argfile_index = flag_index + 1
        if argfile_index >= len(command_args):
            raise argparse.ArgumentTypeError(
                f"recognized ExifTool-style '-stay_open {command_args[flag_index]}' "
                "without required persistent -@ ARGFILE"
            )
        if command_args[argfile_index] != "-@":
            raise argparse.ArgumentTypeError(
                f"recognized ExifTool-style '-stay_open {command_args[flag_index]}' "
                "without following persistent -@ ARGFILE"
            )
        if argfile_index + 1 >= len(command_args):
            raise argparse.ArgumentTypeError(
                f"recognized ExifTool-style '-stay_open {command_args[flag_index]}' "
                "with missing persistent -@ ARGFILE"
            )
        if argfile_index + 2 < len(command_args):
            raise argparse.ArgumentTypeError(
                "public -stay_open currently supports bounded frame execution from "
                "the persistent -@ ARGFILE only; trailing command-line arguments after "
                "-@ ARGFILE must be moved after -common_args or into the ARGFILE"
            )
        argfile = command_args[argfile_index + 1]
        process_mode: StayOpenProcessMode = (
            "persistent_process" if argfile == "-" else "bounded_argfile_replay"
        )
        return TopLevelStayOpenRequest(
            argfile=argfile,
            common_args=command_line.common_args,
            process_mode=process_mode,
        )
    return None


def is_public_subcommand_name(arg: str) -> bool:
    return arg in {
        "read",
        "inspect",
        "write",
        "capabilities",
        "tag-lookup",
        "listgeo",
        "-h",
        "--help",
    }


def run_top_level_stay_open_driver(
    argfile: str,
    parser: argparse.ArgumentParser,
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    process_mode: StayOpenProcessMode | None = None,
    sleeper: StayOpenSleeper | None = None,
    max_empty_polls: int | None = None,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> int:
    if process_mode == "persistent_process":
        if argfile == "-":
            return run_top_level_stay_open_process_loop(
                argfile,
                parser,
                command_runner=command_runner,
                common_args=common_args,
                sleeper=time.sleep if sleeper is None else sleeper,
                max_empty_polls=max_empty_polls,
                trusted_config_effects=trusted_config_effects,
                default_config_disabled=default_config_disabled,
            )
        return run_supervised_disk_stay_open_process_loop(
            argfile,
            parser,
            command_runner=command_runner,
            common_args=common_args,
            sleeper=sleeper,
            max_empty_polls=max_empty_polls,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        ).exit_code
    if argfile == "-":
        return run_top_level_stay_open_process_loop(
            argfile,
            parser,
            command_runner=command_runner,
            common_args=common_args,
            sleeper=time.sleep if sleeper is None else sleeper,
            max_empty_polls=max_empty_polls,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        )
    exit_code = 0
    current_argfile = argfile
    opened_argfiles: set[str] = set()
    while True:
        if current_argfile in opened_argfiles:
            parser.error(
                "public -stay_open bounded argfile switching refuses to reopen "
                f"persistent ARGFILE {current_argfile!r}; ExifTool prevents direct "
                "same-file switching and the bounded driver rejects cycles"
            )
        opened_argfiles.add(current_argfile)
        next_argfile = run_bounded_stay_open_argfile(
            current_argfile,
            parser,
            command_runner=command_runner,
            common_args=common_args,
            exit_code=exit_code,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        )
        exit_code = next_argfile.exit_code
        if next_argfile.argfile is None:
            return exit_code
        current_argfile = next_argfile.argfile


@dataclass(frozen=True)
class StayOpenArgfileStep:
    exit_code: int
    argfile: str | None


@dataclass(frozen=True)
class InMemoryStayOpenRunResult:
    exit_code: int
    status: PersistentStayOpenStatus
    switch_argfile: str | None = None
    include_argfile: str | None = None


class InMemoryStayOpenInputHost:
    """Deterministic input-host implementation for bounded process-loop tests."""

    def __init__(
        self,
        chunks_by_argfile: Mapping[str, Sequence[str]],
        *,
        initial_argfile: str = "-",
    ) -> None:
        self._chunks_by_argfile = {
            argfile: tuple(chunks) for argfile, chunks in chunks_by_argfile.items()
        }
        self._positions = {argfile: 0 for argfile in self._chunks_by_argfile}
        self._argfile = initial_argfile
        self._argfile_stack: list[str] = []
        self._closed = False

    @property
    def argfile(self) -> str:
        return self._argfile

    def read_protocol_chunk(self) -> StayOpenInputChunk:
        if self._closed:
            return StayOpenInputChunk(status="closed")
        chunks = self._chunks_by_argfile.get(self._argfile, ())
        position = self._positions.get(self._argfile, 0)
        if position >= len(chunks):
            return StayOpenInputChunk(status="eof")
        self._positions[self._argfile] = position + 1
        return StayOpenInputChunk(status="data", text=chunks[position])

    def switch_argfile(self, argfile: str) -> None:
        if argfile not in self._chunks_by_argfile:
            raise argparse.ArgumentTypeError(f"Error opening arg file {argfile}")
        self._argfile = argfile
        self._argfile_stack = []
        self._positions.setdefault(argfile, 0)

    def push_argfile(self, argfile: str) -> None:
        if argfile not in self._chunks_by_argfile:
            raise argparse.ArgumentTypeError(f"Error opening arg file {argfile}")
        self._argfile_stack.append(self._argfile)
        self._argfile = argfile
        self._positions.setdefault(argfile, 0)

    def return_from_argfile(self) -> bool:
        if not self._argfile_stack:
            return False
        self._argfile = self._argfile_stack.pop()
        return True

    def close(self) -> None:
        self._closed = True


@dataclass(frozen=True)
class _FileStayOpenInputSource:
    argfile: str
    fd: int | None
    close_fd: bool
    text_reader: StayOpenTextReader | None
    text_reader_strips_bom: bool
    decoder: codecs.IncrementalDecoder


class FileStayOpenInputHost:
    """OS-backed stay-open input owner for stdin or disk ARGFILE reads."""

    def __init__(self, argfile: str, *, read_size: int = STAY_OPEN_READ_SIZE) -> None:
        self._read_size = read_size
        self._fd: int | None = None
        self._close_fd = False
        self._text_reader: StayOpenTextReader | None = None
        self._text_reader_strips_bom = False
        self._source_stack: list[_FileStayOpenInputSource] = []
        self._closed = False
        self._argfile = ""
        decoder_factory = codecs.getincrementaldecoder("utf-8-sig")
        if decoder_factory is None:
            raise RuntimeError("missing utf-8-sig incremental decoder")
        self._decoder: codecs.IncrementalDecoder = decoder_factory()
        self.switch_argfile(argfile)

    @property
    def argfile(self) -> str:
        return self._argfile

    def read_protocol_chunk(self) -> StayOpenInputChunk:
        if self._closed:
            return StayOpenInputChunk(status="closed")
        if self._fd is not None:
            try:
                chunk = os.read(self._fd, self._read_size)
            except OSError as exc:
                raise argparse.ArgumentTypeError("Error reading from ARGFILE") from exc
            if not chunk:
                return StayOpenInputChunk(status="eof")
            return StayOpenInputChunk(status="data", text=self._decoder.decode(chunk))
        if self._text_reader is None:
            return StayOpenInputChunk(status="closed")
        try:
            text = self._text_reader.read(self._read_size)
        except OSError as exc:
            raise argparse.ArgumentTypeError("Error reading from ARGFILE") from exc
        if not text:
            return StayOpenInputChunk(status="eof")
        if self._text_reader_strips_bom:
            text = text.lstrip("\ufeff")
            self._text_reader_strips_bom = False
        return StayOpenInputChunk(status="data", text=text)

    def switch_argfile(self, argfile: str) -> None:
        self._close_current_source()
        self._close_stacked_sources()
        self._open_argfile(argfile)

    def push_argfile(self, argfile: str) -> None:
        if argfile == self._argfile and argfile != "-":
            raise argparse.ArgumentTypeError(
                f"Ignoring request to include the same ARGFILE {argfile}"
            )
        current_source = _FileStayOpenInputSource(
            argfile=self._argfile,
            fd=self._fd,
            close_fd=self._close_fd,
            text_reader=self._text_reader,
            text_reader_strips_bom=self._text_reader_strips_bom,
            decoder=self._decoder,
        )
        self._fd = None
        self._text_reader = None
        self._close_fd = False
        try:
            self._open_argfile(argfile)
        except argparse.ArgumentTypeError:
            self._restore_source(current_source)
            raise
        self._source_stack.append(current_source)

    def return_from_argfile(self) -> bool:
        if not self._source_stack:
            return False
        self._close_current_source()
        self._restore_source(self._source_stack.pop())
        return True

    def _open_argfile(self, argfile: str) -> None:
        decoder_factory = codecs.getincrementaldecoder("utf-8-sig")
        if decoder_factory is None:
            raise RuntimeError("missing utf-8-sig incremental decoder")
        self._decoder = decoder_factory()
        self._argfile = argfile
        self._closed = False
        if argfile == "-":
            try:
                self._fd = sys.stdin.fileno()
            except AttributeError, OSError:
                self._fd = None
                self._text_reader = sys.stdin
                self._text_reader_strips_bom = True
                self._close_fd = False
            else:
                self._text_reader = None
                self._text_reader_strips_bom = False
                self._close_fd = False
            return
        try:
            self._fd = os.open(argfile, os.O_RDONLY)
        except OSError as exc:
            raise argparse.ArgumentTypeError(f"Error opening arg file {argfile}") from exc
        self._text_reader = None
        self._text_reader_strips_bom = False
        self._close_fd = True

    def close(self) -> None:
        if self._closed:
            return
        self._close_current_source()
        self._close_stacked_sources()
        self._closed = True

    def _close_current_source(self) -> None:
        if self._fd is not None:
            if self._close_fd:
                os.close(self._fd)
            self._fd = None
        if self._text_reader is not None and self._argfile != "-":
            self._text_reader.close()
        self._text_reader = None
        self._text_reader_strips_bom = False
        self._close_fd = False

    def _close_stacked_sources(self) -> None:
        while self._source_stack:
            source = self._source_stack.pop()
            if source.fd is not None and source.close_fd:
                os.close(source.fd)
            if source.text_reader is not None and source.argfile != "-":
                source.text_reader.close()

    def _restore_source(self, source: _FileStayOpenInputSource) -> None:
        self._argfile = source.argfile
        self._fd = source.fd
        self._close_fd = source.close_fd
        self._text_reader = source.text_reader
        self._text_reader_strips_bom = source.text_reader_strips_bom
        self._decoder = source.decoder


class PersistentStayOpenProcessOwner:
    """Public-interface owner for a long-lived stay-open protocol session."""

    def __init__(
        self,
        *,
        command_runner: PublicCommandRunner,
        common_args: Sequence[str] = (),
        argfile: str | None = None,
        marker_writer: Callable[[str], None] | None = None,
        trusted_config_effects: PublicTrustedConfigEffects | None = None,
        default_config_disabled: bool = False,
    ) -> None:
        self._marker_writer = marker_writer
        self._session = PersistentStayOpenSession(
            command_runner=command_runner,
            common_args=common_args,
            argfile=argfile,
            option_value_options=top_level_stay_open_value_options(),
            ready_marker_writer=self._write_ready_marker,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        )
        self._exit_code = 0
        self._status: PersistentStayOpenStatus = "open"
        self._switch_argfile: str | None = None
        self._include_argfile: str | None = None

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def status(self) -> PersistentStayOpenStatus:
        return self._status

    @property
    def switch_argfile(self) -> str | None:
        return self._switch_argfile

    @property
    def include_argfile(self) -> str | None:
        return self._include_argfile

    @property
    def argfile(self) -> str | None:
        return self._session.argfile

    def state_snapshot(self) -> PersistentStayOpenStateSnapshot:
        return self._session.state_snapshot()

    def feed(self, chunk: str) -> InMemoryStayOpenRunResult:
        update = self._session.feed(chunk)
        self._apply_update(update)
        return self.result()

    def poll_eof(self) -> InMemoryStayOpenRunResult:
        update = self._session.poll_eof()
        self._apply_update(update)
        return self.result()

    def finish_argfile(self) -> InMemoryStayOpenRunResult:
        update = self._session.finish_argfile()
        self._apply_update(update)
        return self.result()

    def shutdown(self) -> InMemoryStayOpenRunResult:
        update = self._session.shutdown()
        self._apply_update(update)
        return self.result()

    def result(self) -> InMemoryStayOpenRunResult:
        return InMemoryStayOpenRunResult(
            exit_code=self._exit_code,
            status=self._status,
            switch_argfile=self._switch_argfile,
            include_argfile=self._include_argfile,
        )

    def _apply_update(self, update: PersistentStayOpenUpdate) -> None:
        self._status = update.status
        self._switch_argfile = update.switch_argfile
        self._include_argfile = update.include_argfile
        for execution in update.executions:
            self._exit_code = max(self._exit_code, execution.exit_code)

    def _write_ready_marker(self, ready_marker: str) -> None:
        if self._marker_writer is None:
            sys.stdout.write(ready_marker)
            sys.stdout.flush()
            return
        self._marker_writer(ready_marker)


def run_stay_open_process_loop(
    input_host: StayOpenInputHost,
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    marker_writer: Callable[[str], None] | None = None,
    sleeper: StayOpenSleeper = time.sleep,
    max_empty_polls: int | None = None,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> InMemoryStayOpenRunResult:
    """Run a source-backed persistent stay-open owner against an input host."""

    if max_empty_polls is not None and max_empty_polls < 1:
        raise ValueError("max_empty_polls must be positive when provided")

    owner = PersistentStayOpenProcessOwner(
        command_runner=command_runner,
        common_args=common_args,
        argfile=input_host.argfile,
        marker_writer=marker_writer,
        trusted_config_effects=trusted_config_effects,
        default_config_disabled=default_config_disabled,
    )
    empty_polls = 0
    while True:
        chunk = input_host.read_protocol_chunk()
        if chunk.status == "closed":
            return owner.shutdown()
        if chunk.status == "eof":
            if input_host.return_from_argfile():
                result = owner.finish_argfile()
                if result.status == "include_argfile":
                    if result.include_argfile is None:
                        raise argparse.ArgumentTypeError("missing nested ARGFILE for -@ option")
                    input_host.push_argfile(result.include_argfile)
                    continue
                if result.status == "switch_argfile":
                    if result.switch_argfile is None:
                        raise argparse.ArgumentTypeError("missing stay-open switch ARGFILE")
                    input_host.switch_argfile(result.switch_argfile)
                    continue
                if result.status == "shutdown":
                    input_host.close()
                    return result
                continue
            result = owner.poll_eof()
            empty_polls += 1
            if max_empty_polls is not None and empty_polls >= max_empty_polls:
                return result
            sleeper(STAY_OPEN_DISK_POLL_DELAY_SECONDS)
            continue

        empty_polls = 0
        result = owner.feed(chunk.text)
        if result.status == "include_argfile":
            if result.include_argfile is None:
                raise argparse.ArgumentTypeError("missing nested ARGFILE for -@ option")
            input_host.push_argfile(result.include_argfile)
            continue
        if result.status == "switch_argfile":
            if result.switch_argfile is None:
                raise argparse.ArgumentTypeError("missing stay-open switch ARGFILE")
            input_host.switch_argfile(result.switch_argfile)
            continue
        if result.status == "shutdown":
            input_host.close()
            return result


def run_top_level_stay_open_process_loop(
    argfile: str,
    parser: argparse.ArgumentParser,
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    sleeper: StayOpenSleeper = time.sleep,
    max_empty_polls: int | None = None,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> int:
    try:
        input_host = FileStayOpenInputHost(argfile)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    try:
        result = run_stay_open_process_loop(
            input_host,
            command_runner=command_runner,
            common_args=common_args,
            sleeper=sleeper,
            max_empty_polls=max_empty_polls,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        )
    except (argparse.ArgumentTypeError, PersistentStayOpenProtocolError) as exc:
        input_host.close()
        parser.error(str(exc))
    return result.exit_code


def run_supervised_disk_stay_open_process_loop(
    argfile: str,
    parser: argparse.ArgumentParser,
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    marker_writer: Callable[[str], None] | None = None,
    sleeper: StayOpenSleeper | None = None,
    max_empty_polls: int | None = None,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> InMemoryStayOpenRunResult:
    if argfile == "-":
        parser.error(
            "supervised disk -stay_open polling requires a disk ARGFILE; "
            "ExifTool documentation says CONT wakeup is unnecessary for pipe-backed -@ -"
        )
    try:
        input_host = FileStayOpenInputHost(argfile)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    supervisor = StayOpenDiskPollSupervisor()
    loop_sleeper = supervisor.sleep if sleeper is None else sleeper
    try:
        if sleeper is None:
            with supervisor:
                return run_stay_open_process_loop(
                    input_host,
                    command_runner=command_runner,
                    common_args=common_args,
                    marker_writer=marker_writer,
                    sleeper=loop_sleeper,
                    max_empty_polls=max_empty_polls,
                    trusted_config_effects=trusted_config_effects,
                    default_config_disabled=default_config_disabled,
                )
        return run_stay_open_process_loop(
            input_host,
            command_runner=command_runner,
            common_args=common_args,
            marker_writer=marker_writer,
            sleeper=loop_sleeper,
            max_empty_polls=max_empty_polls,
            trusted_config_effects=trusted_config_effects,
            default_config_disabled=default_config_disabled,
        )
    except (argparse.ArgumentTypeError, PersistentStayOpenProtocolError) as exc:
        input_host.close()
        parser.error(str(exc))


def run_in_memory_stay_open_protocol(
    chunks: Sequence[str],
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    argfile: str | None = None,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> InMemoryStayOpenRunResult:
    """Run a deterministic persistent stay-open owner for CLI-compatible tests."""

    owner = PersistentStayOpenProcessOwner(
        command_runner=command_runner,
        common_args=common_args,
        argfile=argfile,
        trusted_config_effects=trusted_config_effects,
        default_config_disabled=default_config_disabled,
    )
    for chunk in chunks:
        result = owner.feed(chunk)
        if result.status in {"shutdown", "switch_argfile"}:
            break
    return owner.result()


@dataclass(frozen=True)
class _BoundedStayOpenReplayResult:
    exit_code: int
    state: StayOpenParseState
    switch_argfile: str | None = None
    shutdown: bool = False


class _BoundedStayOpenArgfileReplay:
    def __init__(
        self,
        parser: argparse.ArgumentParser,
        *,
        command_runner: PublicCommandRunner,
        common_args: Sequence[str],
        trusted_config_effects: PublicTrustedConfigEffects | None = None,
        default_config_disabled: bool = False,
    ) -> None:
        self._parser = parser
        self._command_runner = command_runner
        self._common_args = tuple(common_args)
        self._trusted_config_effects = trusted_config_effects
        self._default_config_disabled = default_config_disabled
        self._waiting_for_switch_argfile = False

    def run_persistent_argfile(self, argfile: str, *, exit_code: int) -> StayOpenArgfileStep:
        result = self._process_argfile(
            argfile,
            state=StayOpenParseState(),
            exit_code=exit_code,
            persistent_argfile=argfile,
            include_final_partial_line=False,
        )
        if result.shutdown:
            return StayOpenArgfileStep(exit_code=result.exit_code, argfile=None)
        if result.switch_argfile is not None:
            return StayOpenArgfileStep(exit_code=result.exit_code, argfile=result.switch_argfile)
        if self._waiting_for_switch_argfile:
            self._parser.error(stay_open_missing_switch_argfile_message())
        return StayOpenArgfileStep(exit_code=result.exit_code, argfile=None)

    def _process_argfile(
        self,
        argfile: str,
        *,
        state: StayOpenParseState,
        exit_code: int,
        persistent_argfile: str,
        include_final_partial_line: bool,
    ) -> _BoundedStayOpenReplayResult:
        try:
            stream_text = read_stay_open_argfile_text(argfile)
        except argparse.ArgumentTypeError as exc:
            self._parser.error(str(exc))
        return self._process_stream_text(
            stream_text,
            state=state,
            exit_code=exit_code,
            persistent_argfile=persistent_argfile,
            include_final_partial_line=include_final_partial_line,
        )

    def _process_stream_text(
        self,
        stream_text: str,
        *,
        state: StayOpenParseState,
        exit_code: int,
        persistent_argfile: str,
        include_final_partial_line: bool,
    ) -> _BoundedStayOpenReplayResult:
        for chunk in _iter_argfile_protocol_chunks(
            stream_text,
            include_final_partial_line=include_final_partial_line,
        ):
            parse_result = parse_stay_open_stream(
                state,
                chunk,
                option_value_options=top_level_stay_open_value_options(),
            )
            state = parse_result.state
            for frame in parse_result.frames:
                result = self._process_frame(
                    frame,
                    exit_code=exit_code,
                    persistent_argfile=persistent_argfile,
                )
                exit_code = result.exit_code
                if result.shutdown or result.switch_argfile is not None:
                    return result
                state = result.state
        return _BoundedStayOpenReplayResult(exit_code=exit_code, state=state)

    def _process_frame(
        self,
        frame: StayOpenFrame,
        *,
        exit_code: int,
        persistent_argfile: str,
    ) -> _BoundedStayOpenReplayResult:
        if frame.control.trigger == "execute":
            if self._waiting_for_switch_argfile:
                self._parser.error(stay_open_missing_switch_argfile_message())
            frame_args = tuple(self._common_args) + frame.args
            effective_frame_args = self._effective_command_args(frame_args)
            exit_code = max(exit_code, self._command_runner(effective_frame_args))
            if should_render_stay_open_ready_marker(effective_frame_args, frame.control.value):
                print(render_ready_marker(frame.control.value), end="")
            return _BoundedStayOpenReplayResult(
                exit_code=exit_code,
                state=StayOpenParseState(),
            )
        if frame.control.trigger == "stay_open":
            return self._process_stay_open_frame(frame, exit_code=exit_code)
        return self._process_argfile_frame(
            frame,
            exit_code=exit_code,
            persistent_argfile=persistent_argfile,
        )

    def _process_stay_open_frame(
        self,
        frame: StayOpenFrame,
        *,
        exit_code: int,
    ) -> _BoundedStayOpenReplayResult:
        if is_stay_open_shutdown_value(frame.control.value):
            if self._waiting_for_switch_argfile:
                self._parser.error(stay_open_missing_switch_argfile_message())
            if frame.args:
                exit_code = max(
                    exit_code,
                    self._command_runner(
                        self._effective_command_args(tuple(self._common_args) + frame.args)
                    ),
                )
            return _BoundedStayOpenReplayResult(
                exit_code=exit_code,
                state=StayOpenParseState(),
                shutdown=True,
            )
        if is_stay_open_continue_value(frame.control.value):
            if frame.args:
                self._parser.error(
                    "public -stay_open bounded argfile switching requires "
                    "'-stay_open True' to be a pure control frame with no "
                    "pending command arguments"
                )
            self._waiting_for_switch_argfile = True
            return _BoundedStayOpenReplayResult(
                exit_code=exit_code,
                state=StayOpenParseState(),
            )
        self._parser.error(stay_open_control_deferred_message(frame))

    def _process_argfile_frame(
        self,
        frame: StayOpenFrame,
        *,
        exit_code: int,
        persistent_argfile: str,
    ) -> _BoundedStayOpenReplayResult:
        if frame.control.value is None:
            self._parser.error("missing ARGFILE for -@ option")
        if self._waiting_for_switch_argfile:
            if frame.args:
                self._parser.error(
                    "public -stay_open bounded argfile switching requires '-@ "
                    "NEWARGFILE' to immediately follow '-stay_open True'"
                )
            if frame.control.value == persistent_argfile and persistent_argfile != "-":
                self._parser.error(
                    "public -stay_open bounded argfile switching refuses to switch "
                    f"to the current persistent ARGFILE {persistent_argfile!r}; ExifTool warns "
                    "and ignores direct same-file switches to avoid endless recursion"
                )
            self._waiting_for_switch_argfile = False
            return _BoundedStayOpenReplayResult(
                exit_code=exit_code,
                state=StayOpenParseState(),
                switch_argfile=frame.control.value,
            )
        return self._process_argfile(
            frame.control.value,
            state=StayOpenParseState(pending_args=frame.args),
            exit_code=exit_code,
            persistent_argfile=persistent_argfile,
            include_final_partial_line=True,
        )

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


def run_bounded_stay_open_argfile(
    argfile: str,
    parser: argparse.ArgumentParser,
    *,
    command_runner: PublicCommandRunner,
    common_args: Sequence[str] = (),
    exit_code: int,
    trusted_config_effects: PublicTrustedConfigEffects | None = None,
    default_config_disabled: bool = False,
) -> StayOpenArgfileStep:
    replay = _BoundedStayOpenArgfileReplay(
        parser,
        command_runner=command_runner,
        common_args=common_args,
        trusted_config_effects=trusted_config_effects,
        default_config_disabled=default_config_disabled,
    )
    return replay.run_persistent_argfile(argfile, exit_code=exit_code)


def _iter_argfile_protocol_chunks(
    text: str,
    *,
    include_final_partial_line: bool,
) -> tuple[str, ...]:
    chunks: list[str] = []
    start = 0
    while True:
        newline_index = text.find("\n", start)
        if newline_index < 0:
            if include_final_partial_line and start < len(text):
                chunks.append(f"{text[start:]}\n")
            return tuple(chunks)
        chunks.append(text[start : newline_index + 1])
        start = newline_index + 1


def read_stay_open_argfile_text(argfile: str) -> str:
    if argfile == "-":
        return sys.stdin.read().lstrip("\ufeff")
    try:
        return Path(argfile).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise argparse.ArgumentTypeError(f"Error opening arg file {argfile}") from exc


def top_level_stay_open_value_options() -> tuple[str, ...]:
    return (
        "-addTagsFromFile",
        "-api",
        "-allTagsFromFile",
        "-c",
        "-charset",
        "-coordFormat",
        "-config",
        "-csvDelim",
        "-d",
        "-dateFormat",
        "-diff",
        "-echo",
        "-echo#",
        "-efile",
        "-efile#",
        "-efile!",
        "-efile#!",
        "-ext",
        "-extension",
        "--ext",
        "--extension",
        "-ext+",
        "-extension+",
        "--extension+",
        "-file",
        "-file#",
        "-fileOrder",
        "-fileOrder#",
        "-geosync",
        "-geotag",
        "-geotime",
        "-globalTimeShift",
        "-gps:geosync",
        "-gps:geotime",
        "-if",
        "-if#",
        "-i",
        "-ignore",
        "-lang",
        "-listItem",
        "-o",
        "-out",
        "-p",
        "-p-",
        "-password",
        "-printFormat",
        "-printFormat-",
        "-require",
        "-sep",
        "-separator",
        "-srcfile",
        "-tag",
        "-tagOut",
        "-tagOut!",
        "-tagOut+",
        "-tagOut+!",
        "-tagOut!+",
        "-tagsFromFile",
        "-textOut",
        "-textOut!",
        "-textOut+",
        "-textOut+!",
        "-textOut!+",
        "-exif:geotime",
        "-itemlist:geotime",
        "-keys:geotime",
        "-quicktime:geotime",
        "-userdata:geotime",
        "-use",
        "-userParam",
        "-xmp:geotime",
        "-W",
        "-W!",
        "-W+",
        "-W+!",
        "-W!+",
        "-Wext",
        "-wm",
        "-writeMode",
        "-w",
        "-w!",
        "-w+",
        "-w+!",
        "-w!+",
        "-x",
        "-exclude",
    )


def is_stay_open_shutdown_value(value: str | None) -> bool:
    return value is not None and value.lower() in {"0", "false"}


def is_stay_open_continue_value(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true"}


def should_render_stay_open_ready_marker(
    args: Sequence[str],
    execute_id: str | None,
) -> bool:
    if any(arg in {"-T", "-table"} for arg in args):
        return False
    return not (execute_id is None and any(arg.lower() in {"-q", "-quiet"} for arg in args))


def stay_open_control_deferred_message(frame: StayOpenFrame) -> str:
    if frame.control.trigger == "argfile":
        return (
            "public -stay_open received a deferred -@ control outside the bounded "
            "argfile replay path; ExifTool treats bare -@ as a non-persistent "
            "nested argfile and returns to the current ARGFILE after it drains"
        )
    return (
        "public -stay_open only supports -execute frames and '-stay_open False' "
        "shutdown frames in the bounded driver"
    )


def stay_open_missing_switch_argfile_message() -> str:
    return (
        "public -stay_open bounded argfile switching requires '-stay_open True' "
        "to be followed by '-@ NEWARGFILE' before any execute or shutdown control"
    )
