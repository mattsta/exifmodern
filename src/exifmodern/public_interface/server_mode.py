"""Opt-in localhost JSON-lines server for the public CLI."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import socketserver
import sys
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
DEFAULT_MAX_LINE_BYTES = 1024 * 1024
DEFAULT_MAX_ARG_COUNT = 512
DEFAULT_MAX_ARG_BYTES = 64 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_READ_TIMEOUT_SECONDS = 30.0
PROTOCOL = "exifmodern-jsonl-v1"

_CLI_CAPTURE_LOCK = threading.Lock()

type ServerJsonScalar = str | int | float | bool | None
type ServerJsonValue = ServerJsonScalar | list[ServerJsonValue] | dict[str, ServerJsonValue]
type ServerJsonObject = dict[str, ServerJsonValue]


@dataclass(frozen=True)
class ServerLimits:
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES
    max_arg_count: int = DEFAULT_MAX_ARG_COUNT
    max_arg_bytes: int = DEFAULT_MAX_ARG_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS


@dataclass(frozen=True)
class CapturedCliResult:
    exit_code: int
    stdout: str
    stderr: str


class JsonLineProtocolError(ValueError):
    """Raised when a client sends a request outside the bounded protocol."""


class _JsonLineServerMixin:
    limits: ServerLimits

    def handle_request_line(self, raw_line: bytes) -> bytes:
        try:
            request = _decode_request(raw_line, self.limits)
            result = _run_public_cli_captured(request.argv)
            response: ServerJsonObject = {
                "protocol": PROTOCOL,
                "ok": result.exit_code == 0,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            if request.request_id is not None:
                response["request_id"] = request.request_id
            response = _enforce_response_limit(response, self.limits)
        except JsonLineProtocolError as exc:
            response = {
                "protocol": PROTOCOL,
                "ok": False,
                "exit_code": 2,
                "stdout": "",
                "stderr": f"{exc}\n",
            }
        return json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"


class _JsonLineRequestHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.request.settimeout(_json_line_server(self.server).limits.read_timeout_seconds)

    def handle(self) -> None:
        while True:
            try:
                server = _json_line_server(self.server)
                line = self.rfile.readline(server.limits.max_line_bytes + 1)
            except TimeoutError:
                self._write_error("request timed out while waiting for a JSON line")
                return
            if not line:
                return
            if len(line) > server.limits.max_line_bytes:
                self._write_error("request line exceeds max_line_bytes")
                return
            response = server.handle_request_line(line)
            self.wfile.write(response)
            self.wfile.flush()

    def _write_error(self, message: str) -> None:
        self.wfile.write(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "ok": False,
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": f"{message}\n",
                },
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        self.wfile.flush()


def _json_line_server(server: socketserver.BaseServer) -> _JsonLineServerMixin:
    if not isinstance(server, _JsonLineServerMixin):
        raise AssertionError("JSON-line request handler attached to incompatible server")
    return server


class ExifModernJsonLineServer(_JsonLineServerMixin, socketserver.ThreadingTCPServer):
    """Bounded TCP server that invokes the existing public CLI in-process."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16
    limits: ServerLimits

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        limits: ServerLimits | None = None,
    ) -> None:
        self.limits = ServerLimits() if limits is None else limits
        super().__init__(server_address, _JsonLineRequestHandler)


class ExifModernUnixJsonLineServer(_JsonLineServerMixin, socketserver.ThreadingUnixStreamServer):
    """Bounded Unix-domain socket server for local public CLI requests."""

    daemon_threads = True
    request_queue_size = 16
    limits: ServerLimits

    def __init__(
        self,
        socket_path: str,
        *,
        limits: ServerLimits | None = None,
    ) -> None:
        self.limits = ServerLimits() if limits is None else limits
        super().__init__(socket_path, _JsonLineRequestHandler)


@dataclass(frozen=True)
class _ClientRequest:
    argv: tuple[str, ...]
    request_id: ServerJsonValue = None


def _decode_request(raw_line: bytes, limits: ServerLimits) -> _ClientRequest:
    try:
        payload = json.loads(raw_line.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise JsonLineProtocolError("request line must be valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise JsonLineProtocolError(f"request line must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise JsonLineProtocolError("request must be a JSON object")
    argv = payload.get("argv")
    if not isinstance(argv, list):
        raise JsonLineProtocolError("request field 'argv' must be a list of strings")
    if len(argv) > limits.max_arg_count:
        raise JsonLineProtocolError("request field 'argv' exceeds max_arg_count")
    parsed_args: list[str] = []
    total_arg_bytes = 0
    for arg in argv:
        if not isinstance(arg, str):
            raise JsonLineProtocolError("request field 'argv' must contain only strings")
        total_arg_bytes += len(arg.encode("utf-8"))
        if total_arg_bytes > limits.max_arg_bytes:
            raise JsonLineProtocolError("request field 'argv' exceeds max_arg_bytes")
        parsed_args.append(arg)
    if parsed_args and parsed_args[0] == "server":
        raise JsonLineProtocolError("nested 'server' requests are not allowed")
    return _ClientRequest(argv=tuple(parsed_args), request_id=payload.get("request_id"))


def _run_public_cli_captured(argv: Sequence[str]) -> CapturedCliResult:
    from exifmodern.public_interface.entrypoint import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    # The existing CLI writes to process-global stdout/stderr. Serialize request
    # execution so concurrent clients cannot interleave captured output.
    with _CLI_CAPTURE_LOCK, _redirect_public_stdio(stdout, stderr):
        try:
            exit_code = main(argv)
        except SystemExit as exc:
            exit_code = _system_exit_code(exc)
    return CapturedCliResult(
        exit_code=exit_code,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )


@contextlib.contextmanager
def _redirect_public_stdio(stdout: TextIO, stderr: TextIO) -> Iterator[None]:
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield


def _system_exit_code(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def _enforce_response_limit(
    response: ServerJsonObject,
    limits: ServerLimits,
) -> ServerJsonObject:
    stdout = response["stdout"]
    stderr = response["stderr"]
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise AssertionError("internal server response capture must be text")
    response_bytes = len(stdout.encode("utf-8")) + len(stderr.encode("utf-8"))
    if response_bytes <= limits.max_response_bytes:
        return response
    limited_response: ServerJsonObject = {
        "protocol": PROTOCOL,
        "ok": False,
        "exit_code": 1,
        "stdout": "",
        "stderr": "captured CLI output exceeds max_response_bytes\n",
    }
    request_id = response.get("request_id")
    if request_id is not None:
        limited_response["request_id"] = request_id
    return limited_response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exifmodern server",
        description="Run an explicit localhost JSON-lines server for public CLI requests.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host; defaults to 127.0.0.1")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="bind port; 0 chooses one")
    parser.add_argument(
        "--unix-socket",
        type=Path,
        default=None,
        help="bind a Unix-domain socket instead of TCP host/port",
    )
    parser.add_argument("--max-line-bytes", default=DEFAULT_MAX_LINE_BYTES, type=int)
    parser.add_argument("--max-arg-count", default=DEFAULT_MAX_ARG_COUNT, type=int)
    parser.add_argument("--max-arg-bytes", default=DEFAULT_MAX_ARG_BYTES, type=int)
    parser.add_argument("--max-response-bytes", default=DEFAULT_MAX_RESPONSE_BYTES, type=int)
    parser.add_argument("--read-timeout-seconds", default=DEFAULT_READ_TIMEOUT_SECONDS, type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        limits = ServerLimits(
            max_line_bytes=_positive_int(args.max_line_bytes, "max-line-bytes"),
            max_arg_count=_positive_int(args.max_arg_count, "max-arg-count"),
            max_arg_bytes=_positive_int(args.max_arg_bytes, "max-arg-bytes"),
            max_response_bytes=_positive_int(args.max_response_bytes, "max-response-bytes"),
            read_timeout_seconds=_positive_float(
                args.read_timeout_seconds,
                "read-timeout-seconds",
            ),
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.unix_socket is not None:
        return run_unix_server(args.unix_socket, limits)
    return run_tcp_server(args.host, args.port, limits)


def run_tcp_server(host_arg: str, port_arg: int, limits: ServerLimits) -> int:
    with ExifModernJsonLineServer((host_arg, port_arg), limits=limits) as server:
        host = server.server_address[0]
        port = server.server_address[1]
        print(
            json.dumps(
                {"protocol": PROTOCOL, "host": host, "port": port},
                separators=(",", ":"),
            ),
            flush=True,
        )
        server.serve_forever()
    return 0


def run_unix_server(socket_path: Path, limits: ServerLimits) -> int:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    try:
        with ExifModernUnixJsonLineServer(socket_path.as_posix(), limits=limits) as server:
            print(
                json.dumps(
                    {"protocol": PROTOCOL, "unix_socket": socket_path.as_posix()},
                    separators=(",", ":"),
                ),
                flush=True,
            )
            server.serve_forever()
    finally:
        with contextlib.suppress(FileNotFoundError):
            socket_path.unlink()
    return 0


def _positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise argparse.ArgumentTypeError(f"--{name} must be positive")
    return value


def _positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise argparse.ArgumentTypeError(f"--{name} must be positive")
    return value
