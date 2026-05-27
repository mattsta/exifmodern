"""Low-overhead console-script entrypoint for ExifModern."""

from __future__ import annotations

import contextlib
import sys

__all__ = ["main"]

_PUBLIC_SUBCOMMAND_HELP: tuple[tuple[str, str], ...] = (
    ("read", "read metadata from files"),
    ("inspect", "inspect file/container structure"),
    ("write", "plan metadata writes"),
    ("server", "run an explicit localhost JSON-lines server"),
    ("capabilities", "show public interface capabilities"),
    ("tag-lookup", "query the package-backed TagLookup catalog"),
    ("listgeo", "list the package-backed Geolocation database"),
    ("package-data", "inspect bundled production data resources"),
)


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not raw_args or raw_args == ["-h"] or raw_args == ["--help"]:
            sys.stdout.write(_startup_help_text())
            return 0
        from exifmodern.public_interface.entrypoint import main as full_main

        return full_main(raw_args)
    except BrokenPipeError:
        with contextlib.suppress(OSError):
            sys.stdout.close()
        return 0


def _startup_help_text() -> str:
    rows = "\n".join(f"    {name:<16}{help_text}" for name, help_text in _PUBLIC_SUBCOMMAND_HELP)
    return (
        "usage: exifmodern [-h]\n"
        "                  {read,inspect,write,server,capabilities,tag-lookup,listgeo,"
        "package-data} ...\n"
        "\n"
        "Read, inspect, and write file metadata with ExifModern.\n"
        "\n"
        "positional arguments:\n"
        "  {read,inspect,write,server,capabilities,tag-lookup,listgeo,package-data}\n"
        f"{rows}\n"
        "\n"
        "options:\n"
        "  -h, --help            show this help message and exit\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
