# Python-Native API

ExifModern provides a Python API for applications that need metadata access
without spawning a subprocess, scraping terminal output, or translating
ExifTool-style JSON back into application objects.

```python
import exifmodern
```

The top-level `exifmodern` package is the recommended starting point for most
applications. It gives you lazy file objects, structured read results, simple
write helpers, staged edit sessions, and in-memory byte reads. The
`exifmodern.public_api` package is the lower-level typed request/result layer
used when an application needs direct control over rendering, traversal,
output routing, duplicate tags, or write planning.

## Quick Start

Read a file and access common tags:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

print(image.ok)
print(image.text("FileType"))
print(image.text("ImageSize"))
print(image.value("EXIF:CreateDate"))
```

Read only selected tags:

```python
import exifmodern

image = exifmodern.open_file(
    "photo.jpg",
    tags=("FileType", "ImageWidth", "ImageHeight", "EXIF:CreateDate"),
)

print(image.values)
```

Read several files in one call:

```python
import exifmodern

result = exifmodern.read_files(
    ("first.jpg", "second.jpg", "third.png"),
    tags=("FileType", "ImageSize", "MIMEType"),
)

for record in result.records:
    print(record.path, record.values)
```

Write a metadata copy to a separate output file:

```python
import exifmodern

result = exifmodern.set_tags(
    "photo.jpg",
    {"Artist": "Ada Lovelace", "Copyright": "Ada Lovelace"},
    output_path="photo-tagged.jpg",
)

if not result.status == "ok":
    for diagnostic in result.diagnostics:
        print(diagnostic.code, diagnostic.message)
```

Stage multiple edits and save in place:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

result = (
    image.edit()
    .set("Artist", "Ada Lovelace")
    .remove_gps()
    .with_preserve_file_times()
    .save_in_place()
)

print(result.status)
print(result.changed_paths)
```

## High-Level vs Lower-Level API

Use the top-level API when you want a compact application interface:

- `exifmodern.open_file()` for a lazy file facade.
- `exifmodern.from_bytes()` for metadata reads from bytes already in memory.
- `exifmodern.read_file()` for a direct `dict`-like value mapping.
- `exifmodern.read_files()` for structured batch reads.
- `exifmodern.read_args()` for ExifTool-style read arguments with native
  structured results.
- `exifmodern.write_file()`, `set_tags()`, `delete_tags()`, and `remove_gps()`
  for immediate write operations.
- `ExifModernFile.edit()` for immutable staged edits.

Use `exifmodern.public_api` when you need explicit request objects:

- Custom output formats such as JSON, XML, CSV, tab, HTML, or PHP.
- Group-name rendering, duplicate tag handling, unknown tag controls, and
  binary-output controls.
- Directory traversal and extension filtering.
- Conditional reads and alternate/source file options.
- Write planning before execution.
- Capability and tag lookup requests.
- Application code that benefits from stable dataclass request/result models.

The lower-level API is still public. It is simply more explicit than the
high-level facade.

## Lazy File Facade

`open_file()` returns an immutable `ExifModernFile`. Constructing it is cheap:
it records the path, tag selection, render options, and fast-scan level. It
does not parse the file immediately.

Metadata is read on first access to lazy properties such as:

- `image.result`
- `image.record`
- `image.values`
- `image.rendered_text`
- `image.rendered_binary`
- `image.status`
- `image.ok`
- `image.diagnostics`

Example:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

# No metadata read has happened yet.
print(image.path)

# First metadata access executes the read.
print(image.values)

# Later accesses reuse the cached result on this facade.
print(image.status)
print(image.diagnostics)
```

The facade is immutable. Methods such as `with_tags()` and `with_render()`
return a new facade with a different request shape:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")
dimensions = image.with_tags("ImageWidth", "ImageHeight")

print(dimensions.values)
```

This design is useful for web applications, workers, and libraries because the
object is safe to pass around without hidden mutation. If you need a fresh
read after a file changes, create a new `ExifModernFile`.

## Accessing Values

Use `value()` when a missing tag is normal:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

gps_latitude = image.value("GPSLatitude")
if gps_latitude is None:
    print("No GPS latitude in this file")
else:
    print(gps_latitude)
```

Use `text()` when you want a display-friendly string for scalar and list
values:

```python
camera = image.text("Model")
size = image.text("ImageSize")
```

Use `require()` when the tag is required for your workflow:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

try:
    width = image.require("ImageWidth")
except KeyError:
    raise RuntimeError("photo.jpg does not contain ImageWidth") from None
```

Use `group_values()` when you selected group-qualified names and want one
group projected into a plain mapping:

```python
import exifmodern

image = exifmodern.open_file(
    "photo.jpg",
    tags=("File:FileType", "File:MIMEType", "EXIF:CreateDate"),
)

print(image.group_values("File"))
```

## Reading One File

`open_file()` returns the full facade. `read_file()` is a convenience helper
that returns only the values mapping:

```python
import exifmodern

values = exifmodern.read_file(
    "photo.jpg",
    tags=("FileType", "ImageWidth", "ImageHeight"),
)

print(values["FileType"])
```

Use `open_file()` when you need status, diagnostics, rendered output, or write
helpers. Use `read_file()` when you just need values.

## Batch Reads

`read_files()` returns a `MetadataReadResult` with one `MetadataReadRecord` per
matched file:

```python
from pathlib import Path

import exifmodern

paths = tuple(Path("uploads").glob("*.jpg"))

result = exifmodern.read_files(
    paths,
    tags=("FileType", "ImageSize", "CreateDate"),
)

if result.diagnostics:
    for diagnostic in result.diagnostics:
        print(diagnostic.code, diagnostic.message)

for record in result.records:
    print(record.path)
    print(record.values)
```

The result is structured; applications do not need to parse stdout.

## Reading Bytes Already in Memory

`from_bytes()` supports applications that already hold the source bytes in
memory:

```python
import exifmodern

def inspect_upload(payload: bytes) -> dict[str, object]:
    image = exifmodern.from_bytes(
        payload,
        suffix=".jpg",
        tags=("FileType", "ImageWidth", "ImageHeight"),
    )
    return dict(image.values)
```

Current production readers are path-oriented. `from_bytes()` therefore uses a
managed temporary file as a bridge, reads through the same production runtime
as file-backed reads, and removes the temporary file after extraction. The
temporary path is not part of the public API and should not be stored.

Prefer `open_file()` for files already on disk. Use `from_bytes()` for upload
handlers, message queues, object-store fetches, and other situations where
serializing to a named application file would be unnecessary boilerplate.

## ExifTool-Style Read Arguments

Use `read_args()` when an application already has ExifTool-style read
arguments but wants native structured results:

```python
import exifmodern

result = exifmodern.read_args(("-G", "-a", "-s", "-ImageWidth", "photo.jpg"))

for record in result.records:
    print(record.values)
```

This is not a subprocess wrapper. The arguments are parsed into ExifModern's
typed public request model and executed through the native runtime.

`read_args()` is useful when an existing system already stores or constructs
ExifTool command-line options. For new Python applications,
prefer `open_file()`, `read_file()`, `read_files()`, or typed
`MetadataReadRequest` objects.

## Rendering Output

The high-level API accepts an `OutputRenderRequest` from
`exifmodern.public_api`:

```python
from pathlib import Path

import exifmodern
from exifmodern.public_api import OutputRenderRequest

image = exifmodern.open_file(
    Path("photo.jpg"),
    tags=("FileType", "ImageWidth", "ImageHeight"),
    render=OutputRenderRequest(format="json", include_group_names=True),
)

print(image.rendered_text)
```

For batch reads:

```python
from exifmodern.public_api import OutputRenderRequest

result = exifmodern.read_files(
    ("first.jpg", "second.jpg"),
    tags=("FileType", "ImageSize"),
    render=OutputRenderRequest(format="csv"),
)

print(result.rendered_text)
```

For most Python applications, use `record.values` for data interchange and
reserve rendered output for compatibility with existing text-oriented
workflows.

## Diagnostics and Errors

ExifModern separates normal metadata/runtime outcomes from programmer errors.

Normal metadata outcomes are reported as diagnostics:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

if not image.ok:
    for diagnostic in image.diagnostics:
        print(f"{diagnostic.code}: {diagnostic.message}")
        if diagnostic.details is not None:
            print(diagnostic.details)
```

Batch results also carry diagnostics:

```python
import exifmodern

result = exifmodern.read_files(("photo.jpg", "missing.jpg"))

for diagnostic in result.diagnostics:
    print(diagnostic.code, diagnostic.message)
```

Programmer errors are raised normally. For example, `require()` raises
`KeyError` when the selected tag is absent:

```python
try:
    serial_number = image.require("SerialNumber")
except KeyError:
    serial_number = "unknown"
```

Recommended application pattern:

```python
import exifmodern

def camera_model(path: str) -> str | None:
    image = exifmodern.open_file(path, tags=("Model",))
    if not image.ok:
        # Log diagnostics for observability, then decide whether to continue.
        for diagnostic in image.diagnostics:
            print(diagnostic.code, diagnostic.message)
        return None
    return image.text("Model")
```

## Write Helpers

High-level write helpers execute immediately:

```python
import exifmodern

result = exifmodern.write_file(
    "photo.jpg",
    assignments={"Artist": "Ada Lovelace"},
    delete_tags=("GPS:All",),
    output_path="photo-public.jpg",
)

print(result.status)
print(result.changed_paths)
```

Convenience wrappers are available:

```python
import exifmodern

exifmodern.set_tags(
    "photo.jpg",
    {"Artist": "Ada Lovelace"},
    output_path="photo-tagged.jpg",
)

exifmodern.delete_tags(
    "photo.jpg",
    "GPS:All",
    "SerialNumber",
    output_path="photo-sanitized.jpg",
)

exifmodern.remove_gps(
    "photo.jpg",
    output_path="photo-no-location.jpg",
)
```

If `output_path` is omitted, the request uses the selected write policy and the
runtime's default output routing. For explicit, easy-to-review application
code, pass `output_path` when you want a new file and use staged
`save_in_place()` when you intentionally want to modify the source file.

## Staged Edit Sessions

`ExifModernFile.edit()` creates an immutable edit session. Each edit method
returns a new session with one more pending operation. No file bytes are
written until `save()` or `save_in_place()` is called.

Save to a separate file:

```python
import exifmodern

image = exifmodern.open_file("photo.jpg")

edit = (
    image.edit()
    .set("Artist", "Ada Lovelace")
    .delete("SerialNumber")
    .remove_gps()
)

result = edit.save(output_path="photo-public.jpg")
print(result.status)
```

Save in place:

```python
import exifmodern

result = (
    exifmodern.open_file("photo.jpg")
    .edit()
    .remove_gps()
    .save_in_place()
)

print(result.changed_paths)
```

Preserve file times when supported by the selected write route:

```python
result = (
    exifmodern.open_file("photo.jpg")
    .edit()
    .set("Artist", "Ada Lovelace")
    .with_preserve_file_times()
    .save(output_path="photo-tagged.jpg")
)
```

Inspect the typed write request without executing it:

```python
image = exifmodern.open_file("photo.jpg")

request = image.edit().remove_gps().plan(output_path="photo-public.jpg")
print(request.deletes)
print(request.write_output_file)
```

This is the preferred pattern when your application wants a review/approval
step before writes are executed.

## Lower-Level Typed API

The lower-level API exposes dataclass request and result models:

```python
from pathlib import Path

from exifmodern.public_api import (
    MetadataReadRequest,
    OutputRenderRequest,
    read_metadata,
)

request = MetadataReadRequest(
    paths=(Path("photo.jpg"),),
    tags=("File:FileType", "Composite:ImageSize"),
    render=OutputRenderRequest(
        format="json",
        include_group_names=True,
        allow_duplicate_tags=True,
    ),
)

result = read_metadata(request)

print(result.status)
print(result.rendered_text)
print(result.records[0].values)
```

Write with an explicit request:

```python
from pathlib import Path

from exifmodern.public_api import (
    MetadataAssignment,
    MetadataWriteRequest,
    OutputWriteFileRouting,
    write_metadata,
)

request = MetadataWriteRequest(
    paths=(Path("photo.jpg"),),
    assignments=(
        MetadataAssignment(tag="Artist", value="Ada Lovelace", order_index=0),
    ),
    deletes=("GPS:All",),
    delete_order_indexes=(0,),
    write_output_file=OutputWriteFileRouting(
        output_path_template="photo-public.jpg",
    ),
)

result = write_metadata(request)
print(result.status)
```

Plan a write without executing it:

```python
from exifmodern.public_api import plan_metadata_write

plan = plan_metadata_write(request)
print(plan.status)
print(plan.diagnostics)
```

Use the typed API when you want stable, explicit request objects that can be
validated, serialized by your own application, logged, reviewed, or converted
from another system.

## Capability and Tag Lookup APIs

Applications can query the production capability surface:

```python
from exifmodern.public_api import CapabilityQueryRequest, query_capabilities

result = query_capabilities(
    CapabilityQueryRequest(
        tag_names=("ImageWidth", "CreateDate"),
        writable_tag_names=("Artist", "GPS:All"),
    )
)

for capability in result.capabilities:
    print(capability.name, capability.status, capability.summary)
```

For tag lookup details, use `PublicTagLookupRequest` and `query_tag_lookup()`
when your application needs to inspect tag existence or writable selections
directly.

## File Inspection

`inspect_file()` provides a lower-level file identification surface:

```python
from pathlib import Path

from exifmodern.public_api import FileInspectRequest, inspect_file

result = inspect_file(FileInspectRequest(paths=(Path("photo.jpg"),)))

for record in result.records:
    print(record.file_type)
    print(record.values)
```

Use this when you need detection/structure information rather than normal
rendered metadata.

## Application Integration Patterns

Web upload handler:

```python
import exifmodern

def metadata_for_upload(payload: bytes, filename: str) -> dict[str, object]:
    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    image = exifmodern.from_bytes(
        payload,
        suffix=suffix,
        tags=("FileType", "MIMEType", "ImageSize"),
    )
    if not image.ok:
        return {
            "ok": False,
            "diagnostics": [
                {"code": item.code, "message": item.message}
                for item in image.diagnostics
            ],
        }
    return {"ok": True, "metadata": dict(image.values)}
```

Background indexing job:

```python
from pathlib import Path

import exifmodern

def index_directory(root: Path) -> list[dict[str, object]]:
    paths = tuple(root.glob("*.jpg"))
    result = exifmodern.read_files(
        paths,
        tags=("FileName", "Model", "CreateDate", "ImageSize"),
    )
    return [
        {"path": str(record.path), **dict(record.values)}
        for record in result.records
    ]
```

Privacy export helper:

```python
from pathlib import Path

import exifmodern

def public_copy(source: Path, destination: Path) -> bool:
    result = (
        exifmodern.open_file(source)
        .edit()
        .remove_gps()
        .delete("SerialNumber")
        .save(output_path=destination)
    )
    return result.status == "ok"
```

Compatibility bridge for existing argument lists:

```python
import exifmodern

def run_legacy_read(args: tuple[str, ...]) -> list[dict[str, object]]:
    result = exifmodern.read_args(args)
    return [dict(record.values) for record in result.records]
```

## Performance Notes

Constructing an `ExifModernFile` is cheap. The read is deferred until metadata
is accessed, and the result is cached on that facade instance.

Recommended practices:

- Select tags when you only need a small subset.
- Use `read_files()` for batches instead of creating many independent control
  paths in application code.
- Prefer file-backed reads for files already on disk.
- Use `from_bytes()` for in-memory uploads or object-store payloads, knowing it
  currently bridges through a managed temporary file.
- Create a new facade when you need to observe file changes after a write.
- Use diagnostics for observability; do not treat every non-empty diagnostic
  list as an exception.

`fast_scan_level` is available on high-level read helpers for workflows that
want faster, more selective scanning where supported:

```python
image = exifmodern.open_file(
    "photo.jpg",
    tags=("FileType", "ImageSize"),
    fast_scan_level=1,
)
```

Exact behavior depends on the file format and selected metadata surface.

## API Stability

For application code, prefer these stable top-level exports:

- `ExifModernFile`
- `ExifModernBytes`
- `ExifModernEdit`
- `open_file()`
- `from_bytes()`
- `read_file()`
- `read_bytes()`
- `read_files()`
- `read_args()`
- `write_file()`
- `set_tags()`
- `delete_tags()`
- `remove_gps()`

For typed integrations, use the public dataclasses and functions exported from
`exifmodern.public_api`, including:

- `MetadataReadRequest`
- `MetadataReadResult`
- `MetadataReadRecord`
- `MetadataWriteRequest`
- `MetadataWriteResult`
- `MetadataAssignment`
- `OutputRenderRequest`
- `OutputWriteFileRouting`
- `Diagnostic`
- `read_metadata()`
- `write_metadata()`
- `plan_metadata_write()`
- `inspect_file()`
- `query_capabilities()`
- `query_tag_lookup()`

Avoid importing modules below `exifmodern.formats`, `exifmodern.services`, or
other implementation packages unless their documentation explicitly identifies
them as public. The supported application contract is the top-level
`exifmodern` package plus `exifmodern.public_api`.
