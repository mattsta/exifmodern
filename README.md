# ExifModern

ExifModern is a modern Python metadata command line tool and runtime library for
ExifTool-compatible read, inspect, and write workflows.

The production package installs the user-facing `exifmodern` command. Repository
maintenance, comparison, and release-validation tooling is kept outside the
published wheel so `uv tool run exifmodern` stays focused on normal metadata
usage.

## Install

ExifModern requires Python 3.14 or newer.

```sh
uv tool install exifmodern
```

Run without installing:

```sh
uv tool run exifmodern --help
```

## Command Line

Read metadata:

```sh
exifmodern read image.jpg
exifmodern read --format json image.jpg
exifmodern read -G -a -s image.jpg
```

Inspect container structure:

```sh
exifmodern inspect video.mp4
```

Plan or execute supported metadata writes:

```sh
exifmodern write --set XMP:Title="Example title" image.jpg
exifmodern write --delete XMP:Title image.jpg
exifmodern write --set XMP:Title="Example title" -o edited.jpg image.jpg
```

Query bundled metadata catalogs:

```sh
exifmodern capabilities
exifmodern tag-lookup --tag Make
exifmodern listgeo --json
```

For repeated command-style calls from non-Python programs, run an explicit
local ExifModern backend once and send each command through the lightweight
`exifc` client. This preserves normal `exifmodern` CLI semantics while avoiding
Python startup for every request:

```sh
# Terminal 1: start the Python backend on loopback.
exifmodern server --host 127.0.0.1 --port 8765

# Terminal 2: send CLI arguments through the already-running backend.
exifc --host 127.0.0.1 --port 8765 -- read --format json image.jpg
exifc --host 127.0.0.1 --port 8765 -- -ver
```

The server speaks bounded newline-delimited JSON over localhost and returns the
same stdout, stderr, and exit-code shape as the public CLI. The Rust client is
intentionally thin: it connects, sends one request, prints the response streams,
and exits with the backend's exit code.

For full option details:

```sh
exifmodern read --help
exifmodern write --help
```

The public release includes fuller user documentation:

- `docs/cli.md`: command-line usage and output modes.
- `docs/python-native-api.md`: Python file, bytes, batch, and typed APIs.
- `docs/write-workflows.md`: write helpers, staged edits, and in-place safety.
- `docs/package-data.md`: bundled runtime databases and deployment notes.
- `docs/performance.md`: benchmark utility and current local ExifTool-vs-
  ExifModern latency snapshot.
- `docs/release-model.md`: public snapshot contents and release packaging
  boundaries.

## Python API

ExifModern exposes a Python-native API so applications can read metadata
without spawning a subprocess or parsing ExifTool-style stdout.

The ergonomic top-level API is file-oriented and lazy:

```python
from pathlib import Path

import exifmodern

image = exifmodern.open_file(Path("image.jpg"))

print(image.status)
print(image.value("FileType"))
print(image.require("ImageWidth"))
print(image.text("CreateDate"))
print(image.diagnostics)
```

Batch reads return structured public API results:

```python
import exifmodern

result = exifmodern.read_files(
    ("first.jpg", "second.jpg"),
    tags=("ImageWidth", "ImageHeight"),
)

for record in result.records:
    print(record.path, record.values)
```

In-memory image bytes can be read without creating a user-managed file:

```python
import exifmodern

with open("image.jpg", "rb") as file:
    image = exifmodern.from_bytes(file.read(), suffix=".jpg")

print(image.value("FileType"))
print(image.value("ImageWidth"))
```

ExifTool-style read arguments can also be parsed into structured Python
results:

```python
import exifmodern

result = exifmodern.read_args(("-G", "-s", "-ImageWidth", "image.jpg"))
print(result.records[0].values)
```

Immediate file-backed writes use the same structured native writer as the CLI.
They execute when called, so pass an explicit `output_path` when you want a new
file:

```python
import exifmodern

result = exifmodern.set_tags(
    "image.jpg",
    {
        "EXIF:Artist": "Example Artist",
        "XMP-dc:Title": "Example title",
    },
    output_path="edited.jpg",
)

if result.status != "ok":
    for diagnostic in result.diagnostics:
        print(diagnostic.code, diagnostic.message)
```

Delete helpers expose ExifTool-style tag/group delete requests:

```python
import exifmodern

exifmodern.delete_tags("image.jpg", "GPS:All", output_path="without-gps.jpg")
exifmodern.open_file("image.jpg").remove_gps(output_path="without-gps.jpg")
```

For staged edits, use `image.edit()`. Edit methods accumulate operations only;
no bytes are written until `save()` or `save_in_place()`:

```python
import exifmodern

image = exifmodern.open_file("image.jpg")

edit = (
    image.edit()
    .remove_gps()
    .set("EXIF:Artist", "Example Artist")
    .set("XMP-dc:Title", "Example title")
)

# Safe explicit-output save.
result = edit.save(output_path="edited.jpg")

# Destructive source-file overwrite is explicit.
in_place_result = edit.save_in_place()
```

Unsupported write routes return structured diagnostics rather than pretending
to succeed.

The lower-level typed request/result API is available from
`exifmodern.public_api`:

```python
from pathlib import Path

from exifmodern.public_api import MetadataReadRequest, OutputRenderRequest, read_metadata

result = read_metadata(
    MetadataReadRequest(
        paths=(Path("image.jpg"),),
        tags=("File:ImageWidth", "Composite:ImageSize"),
        render=OutputRenderRequest(include_group_names=True, format="json"),
    )
)
print(result.rendered_text)
```

See `docs/python-native-api.md` for the API architecture and CLI convergence
model in the public release documentation.

## Production Package Boundary

The published package is intended to contain the runtime CLI, public API,
format handlers, bundled lookup data, and supporting services required for
normal metadata operations.

The source repository also contains maintainership systems used to compare
behavior against upstream ExifTool, generate artifacts, and validate release
readiness. Those systems are intentionally excluded from the production wheel
and are not part of the installed user interface.

## Performance Benchmarks

Development releases include a reusable local benchmark utility:

```sh
uv run python scripts/benchmark-exiftool-vs-exifmodern.py \
  --warmups 3 \
  --iterations 10 \
  --max-files 20 \
  --path-list artifacts/benchmarks/public-benchmark-paths.txt \
  --timeout 30
```

The benchmark compares local `../exiftool/exiftool` against `uv run
exifmodern` for common startup, catalog, and file-read scenarios, writing JSON
and Markdown reports under `artifacts/benchmarks/`. The release path list covers
representative `MP4`, `JPG`, `MOV`, `PNG`, `WEBP`, `PDF`, and `RW2` files;
replace it with an equivalent local path list when those local fixtures are not
available. Current local CLI subprocess measurements show ExifTool remains faster on the sampled
single-command paths; ExifModern's main performance opportunity is the
Python-native API path where applications avoid repeated subprocess startup and
stdout parsing.

### Low-Latency Local Client

`exifc` is the optional Rust client for the persistent `exifmodern server`
backend. It is useful when an application wants process-style command execution
but cannot use the Python API directly.

Build from a source checkout:

```sh
cargo build --release --manifest-path tools/exifmodern_rust_client/Cargo.toml
```

Install the resulting binary somewhere on `PATH`:

```sh
install -m 0755 tools/exifmodern_rust_client/target/release/exifc ~/.local/bin/exifc
```

Run the backend and client:

```sh
exifmodern server --host 127.0.0.1 --port 8765
exifc --host 127.0.0.1 --port 8765 -- read image.jpg
exifc --host 127.0.0.1 --port 8765 -- write --delete GPS:All -o clean.jpg image.jpg
```

Use the Python API for in-process Python applications; use `exifc` when a
separate local process needs near-zero startup latency without parsing a custom
protocol itself.

## Compatibility

ExifModern follows ExifTool-compatible behavior for the supported public
interface. ExifTool is the metadata tool created and maintained by Phil Harvey;
ExifModern is a separate modern Python implementation designed for compatible
operation.
