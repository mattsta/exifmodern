# Write Workflows

ExifModern exposes metadata writes through one structured engine used by both
the command line and the Python API. The write surface is intentionally
explicit: you describe the tags to set or delete, choose whether to write a new
file or modify the source, and then inspect a structured result.

This guide focuses on production-safe write usage. It does not promise that
every ExifTool write route is already executable. When ExifModern cannot safely
execute a route yet, it returns a structured diagnostic instead of pretending
success.

## Mental Model

A write request has four parts:

- The source file or files.
- Assignments such as `EXIF:Artist=Jane Example`.
- Deletes such as `GPS:All` or `XMP-dc:Title`.
- A write policy, either writing a separate output file or intentionally
  replacing the source.

All write results include:

- `status`: `"ok"`, `"unsupported"`, `"deferred"`, or `"condition_failed"`.
- `changed_paths`: files ExifModern reports as changed.
- `diagnostics`: machine-readable explanations for unsupported or deferred
  routes.
- `parsed_operations`: how ExifModern understood the request.

The CLI prints this result as JSON. The Python API returns a typed
`MetadataWriteResult`.

## Recommended Safety Pattern

Use a copy first, especially while building automation:

```sh
cp image.jpg image.work.jpg
exifmodern write --delete GPS:All --set EXIF:Artist="Jane Example" image.work.jpg
exifmodern read image.work.jpg
```

For production scripts, prefer writing to a new path first:

```sh
exifmodern write \
  --delete GPS:All \
  --set XMP-dc:Title="Web ready copy" \
  --output-file image.public.jpg \
  image.jpg
```

Only use source replacement once the exact operation is proven on copies:

```sh
exifmodern write \
  --delete GPS:All \
  --overwrite-original \
  image.jpg
```

## CLI Quick Start

Set one tag:

```sh
exifmodern write --set EXIF:Artist="Jane Example" image.jpg
```

Set multiple tags:

```sh
exifmodern write \
  --set EXIF:Artist="Jane Example" \
  --set XMP-dc:Title="Launch image" \
  --set XMP-dc:Description="Edited for public release" \
  image.jpg
```

Delete one tag:

```sh
exifmodern write --delete XMP-dc:Title image.jpg
```

Delete a group:

```sh
exifmodern write --delete GPS:All image.jpg
```

Write to a new file instead of modifying the source:

```sh
exifmodern write \
  --set XMP-dc:Title="Edited copy" \
  --output-file edited.jpg \
  image.jpg
```

Request replacement of the source file:

```sh
exifmodern write \
  --set XMP-dc:Title="Edited in place" \
  --overwrite-original \
  image.jpg
```

Request ExifTool's separate in-place attribute-preserving mode:

```sh
exifmodern write \
  --set XMP-dc:Title="Edited in place" \
  --overwrite-original-in-place \
  image.jpg
```

`--overwrite-original-in-place` is parsed separately because ExifTool gives it
distinct filesystem semantics. If a route cannot honor those semantics yet,
ExifModern reports a diagnostic instead of silently falling back to another
policy.

## Understanding CLI Output

`exifmodern write` prints JSON. Treat that JSON as the authority:

```sh
exifmodern write --delete GPS:All --output-file without-gps.jpg image.jpg
```

Example shape:

```json
{
  "status": "ok",
  "operation": "write",
  "paths": ["image.jpg"],
  "parsed_operations": [
    {
      "operation": "delete",
      "target": {
        "raw": "GPS:All",
        "tag_name": "All",
        "group_chain": ["GPS"],
        "target_kind": "all"
      },
      "value": null
    }
  ],
  "changed_paths": ["without-gps.jpg"],
  "diagnostics": []
}
```

If the route is not executable, the output is still structured:

```json
{
  "status": "unsupported",
  "diagnostics": [
    {
      "code": "unsupported_public_write_shape",
      "message": "Public write route is not supported by the current native writer."
    }
  ]
}
```

For automation, fail unless `status` is `"ok"` and `diagnostics` is empty or
contains only warnings your application explicitly accepts.

## Checking a Result in Shell Scripts

Use `jq` or your language's JSON parser. A shell script should not scrape human
text:

```sh
result_file="$(mktemp)"

if exifmodern write --delete GPS:All --output-file public.jpg image.jpg > "$result_file"; then
  status="$(jq -r '.status' "$result_file")"
  if [ "$status" = "ok" ]; then
    exifmodern read public.jpg
  else
    jq '.diagnostics' "$result_file" >&2
    exit 1
  fi
else
  cat "$result_file" >&2
  exit 1
fi
```

For batch jobs, store the full JSON result next to logs. It contains the parsed
request and the route diagnostics needed to debug failed writes.

## `output_path` vs In-Place Replacement

There are two safe write styles.

### Write a new output file

Use `--output-file` on the CLI or `output_path=` in Python:

```sh
exifmodern write --delete GPS:All --output-file public.jpg source.jpg
```

```python
import exifmodern

result = exifmodern.remove_gps("source.jpg", output_path="public.jpg")
```

This is the recommended default for applications because the original source
path remains available if the operation fails or the output is not what you
expected.

### Replace the source file

Use `--overwrite-original` on the CLI or `policy="overwrite_original"` in
Python:

```sh
exifmodern write --delete GPS:All --overwrite-original image.jpg
```

```python
import exifmodern

result = exifmodern.remove_gps(
    "image.jpg",
    policy="overwrite_original",
)
```

The object-oriented staged API has a clearer dedicated method:

```python
import exifmodern

result = exifmodern.open_file("image.jpg").edit().remove_gps().save_in_place()
```

Use in-place replacement only when your program has already established its own
backup or rollback policy.

## Preserve File Times

ExifTool users often rely on `-P` to preserve filesystem modification times.
ExifModern parses this as:

```sh
exifmodern write \
  --preserve-file-times \
  --set EXIF:Artist="Jane Example" \
  image.jpg
```

Python equivalent:

```python
import exifmodern

result = exifmodern.write_file(
    "image.jpg",
    assignments={"EXIF:Artist": "Jane Example"},
    preserve_file_times=True,
)
```

The preserve request is route-sensitive. If the selected native writer cannot
guarantee timestamp preservation, the result includes a diagnostic such as
`unsupported_public_preserve_file_times_route`. Do not assume timestamp
preservation succeeded unless the write result is `"ok"` for the route you ran.

## Deleting GPS Data

The common public workflow is deleting the GPS group:

```sh
exifmodern write --delete GPS:All --output-file without-gps.jpg image.jpg
```

Python immediate helper:

```python
import exifmodern

result = exifmodern.remove_gps("image.jpg", output_path="without-gps.jpg")
```

Object helper:

```python
import exifmodern

image = exifmodern.open_file("image.jpg")
result = image.remove_gps(output_path="without-gps.jpg")
```

Staged edit:

```python
import exifmodern

edit = exifmodern.open_file("image.jpg").edit().remove_gps()
result = edit.save(output_path="without-gps.jpg")
```

Always verify:

```sh
exifmodern read without-gps.jpg | grep GPS
```

For Python verification:

```python
import exifmodern

after = exifmodern.open_file("without-gps.jpg")
remaining_gps = after.group_values("GPS")
if remaining_gps:
    raise RuntimeError(f"GPS tags remain: {remaining_gps}")
```

## Deleting Tags and Groups

Delete one tag:

```sh
exifmodern write --delete XMP-dc:Title image.jpg
```

Delete multiple tags:

```sh
exifmodern write \
  --delete XMP-dc:Title \
  --delete XMP-dc:Description \
  --delete EXIF:Artist \
  image.jpg
```

Delete a group:

```sh
exifmodern write --delete GPS:All image.jpg
```

Python:

```python
import exifmodern

result = exifmodern.delete_tags(
    "image.jpg",
    "XMP-dc:Title",
    "XMP-dc:Description",
    "EXIF:Artist",
    output_path="stripped.jpg",
)
```

Group deletes are more powerful than scalar deletes and may route to different
format writers. Check diagnostics before assuming a group delete was executable
for a given file type.

## Setting Tags

CLI:

```sh
exifmodern write \
  --set EXIF:Artist="Jane Example" \
  --set XMP-dc:Title="Portfolio image" \
  --output-file titled.jpg \
  image.jpg
```

Python:

```python
import exifmodern

result = exifmodern.set_tags(
    "image.jpg",
    {
        "EXIF:Artist": "Jane Example",
        "XMP-dc:Title": "Portfolio image",
    },
    output_path="titled.jpg",
)
```

Values are passed as strings through the public convenience API. Format-specific
writers may validate, normalize, or reject values. For example, GPS coordinate
writes require a value shape the GPS writer can parse; unsupported shapes return
diagnostics rather than ambiguous partial writes.

## List Values

The CLI accepts `--separator` to describe list splitting for supported list
write routes:

```sh
exifmodern write \
  --separator "; " \
  --set XMP-dc:Subject="travel; launch; public" \
  image.jpg
```

The staged Python API exposes list-style operations:

```python
import exifmodern

edit = (
    exifmodern.open_file("image.jpg")
    .edit()
    .add("XMP-dc:Subject", "travel")
    .add("XMP-dc:Subject", "launch")
    .delete_value("XMP-dc:Subject", "draft")
)

result = edit.save(output_path="keywords.jpg")
```

List mutation support is route-specific. If a writer cannot execute a requested
list operation for the target file, the result reports the unsupported route.

## Python Immediate Writes

Immediate helpers execute as soon as you call them:

```python
import exifmodern

result = exifmodern.write_file(
    "image.jpg",
    assignments={
        "EXIF:Artist": "Jane Example",
        "XMP-dc:Title": "Launch image",
    },
    delete_tags=("GPS:All",),
    output_path="public.jpg",
)
```

Specialized helpers:

```python
import exifmodern

title_result = exifmodern.set_tags(
    "image.jpg",
    {"XMP-dc:Title": "Launch image"},
    output_path="titled.jpg",
)

delete_result = exifmodern.delete_tags(
    "titled.jpg",
    "GPS:All",
    output_path="without-gps.jpg",
)

gps_result = exifmodern.remove_gps(
    "image.jpg",
    output_path="without-gps.jpg",
)
```

Result handling:

```python
def require_write_ok(result):
    if result.status != "ok":
        for diagnostic in result.diagnostics:
            print(f"{diagnostic.code}: {diagnostic.message}")
            if diagnostic.details is not None:
                print(diagnostic.details)
        raise RuntimeError(f"metadata write failed: {result.status}")


require_write_ok(gps_result)
```

## Object Helpers

`open_file()` returns a lazy metadata view. Its write helpers are convenience
wrappers around immediate writes:

```python
import exifmodern

image = exifmodern.open_file("image.jpg")

result = image.set_tags(
    {
        "EXIF:Artist": "Jane Example",
        "XMP-dc:Title": "Portfolio image",
    },
    output_path="portfolio.jpg",
)
```

Important: immediate object helpers do not mutate the existing read view. If
you want to inspect the edited file, open the output path:

```python
result = image.remove_gps(output_path="without-gps.jpg")

if result.status == "ok":
    edited = exifmodern.open_file("without-gps.jpg")
    print(edited.values)
```

## Staged Edits

Use staged edits when your application needs to build a write request across
multiple steps before saving.

```python
import exifmodern

image = exifmodern.open_file("image.jpg")

edit = (
    image.edit()
    .remove_gps()
    .set("EXIF:Artist", "Jane Example")
    .set("XMP-dc:Title", "Public launch image")
)

request = edit.plan(output_path="public.jpg")
print(request.assignments)
print(request.deletes)

result = edit.save(output_path="public.jpg")
```

`ExifModernEdit` is immutable. Each method returns a new edit session:

```python
import exifmodern

base = exifmodern.open_file("image.jpg").edit().remove_gps()

web = base.set("XMP-dc:Title", "Web copy")
archive = base.set("XMP-dc:Title", "Archive copy")

web_result = web.save(output_path="web.jpg")
archive_result = archive.save(output_path="archive.jpg")
```

This makes staged edits safe for branching workflows, job queues, and retry
systems because the base edit is not modified by later calls.

## In-Place Staged Edits

For in-place replacement:

```python
import exifmodern

result = (
    exifmodern.open_file("image.jpg")
    .edit()
    .remove_gps()
    .set("EXIF:Artist", "Jane Example")
    .save_in_place()
)
```

For preserve-time intent:

```python
import exifmodern

result = (
    exifmodern.open_file("image.jpg")
    .edit()
    .with_preserve_file_times()
    .set("EXIF:Artist", "Jane Example")
    .save(output_path="preserved-time-copy.jpg")
)
```

Use `save_in_place()` only when source replacement is the desired behavior.
For reviewable workflows, use `save(output_path=...)`.

## Building a Safe Batch Processor

This pattern writes new files and leaves originals untouched:

```python
from pathlib import Path

import exifmodern


def require_write_ok(result):
    if result.status != "ok":
        diagnostics = [
            f"{diagnostic.code}: {diagnostic.message}"
            for diagnostic in result.diagnostics
        ]
        raise RuntimeError("\n".join(diagnostics))


source_dir = Path("incoming")
output_dir = Path("public")
output_dir.mkdir(exist_ok=True)

for source in source_dir.glob("*.jpg"):
    output = output_dir / source.name
    result = (
        exifmodern.open_file(source)
        .edit()
        .remove_gps()
        .set("XMP-dc:Rights", "Copyright Jane Example")
        .save(output_path=output)
    )
    require_write_ok(result)
```

For an in-place batch, build your own backups first:

```python
from pathlib import Path
from shutil import copy2

import exifmodern


for source in Path("incoming").glob("*.jpg"):
    backup = source.with_suffix(source.suffix + ".bak")
    copy2(source, backup)

    result = exifmodern.remove_gps(source, policy="overwrite_original")
    if result.status != "ok":
        copy2(backup, source)
        raise RuntimeError(result.diagnostics)
```

## Checking Results After Writes

CLI:

```sh
exifmodern write --delete GPS:All --output-file public.jpg image.jpg
exifmodern read public.jpg
exifmodern read -G public.jpg
```

Python:

```python
import exifmodern

result = exifmodern.remove_gps("image.jpg", output_path="public.jpg")
if result.status != "ok":
    raise RuntimeError(result.diagnostics)

edited = exifmodern.open_file("public.jpg")
if edited.group_values("GPS"):
    raise RuntimeError("GPS metadata still present")
```

For applications, validate the specific tags you changed rather than comparing
entire metadata dumps. Some formats contain timestamps, offsets, derived
values, or normalized values that can differ even when the intended edit is
correct.

## Unsupported and Deferred Routes

ExifModern is built to avoid fake success. A write can fail because:

- The file type is recognized but the selected writer is not implemented yet.
- The tag exists but that write shape is not owned by a safe native writer.
- The request mixes write families that must preserve ExifTool ordering
  semantics and cannot yet be executed safely together.
- The requested backup, preserve-time, or in-place policy cannot be guaranteed
  for the selected route.
- The value shape is invalid for the target writer.

Handle this directly:

```python
import exifmodern

result = exifmodern.set_tags(
    "movie.mp4",
    {"QuickTime:Title": "Launch clip"},
    output_path="movie-edited.mp4",
)

if result.status != "ok":
    for diagnostic in result.diagnostics:
        print(diagnostic.code)
        print(diagnostic.message)
        print(diagnostic.details)
```

Do not treat unsupported or deferred write responses as success. They mean
ExifModern parsed the request and intentionally refused execution because the
selected route is not safely executable by the current native writer.

## Troubleshooting

### The command succeeded but my script did not see text output

Writes emit JSON, not human tag text. Parse `.status`, `.changed_paths`, and
`.diagnostics`.

### I used `--output-file` and the output already exists

Output routing uses an explicit overwrite policy. If a route refuses
to replace an existing output path, write to a fresh path or remove the target
only after your application has decided that is safe.

### I asked for `--preserve-file-times` and got a diagnostic

The selected writer cannot guarantee ExifTool-compatible timestamp preservation
for that route yet. Either omit preserve-time behavior, copy timestamps in your
application after a successful write, or choose a write route that reports
`status == "ok"` with your preserve request.

### I tried a tag and got `unsupported_*`

The tag was parsed but not executable for the selected format/write family.
Inspect `diagnostics[].details`; many diagnostics include the unsupported tag
or path and sometimes the supported route shape.

### I mixed unrelated writes and got a shape diagnostic

Split the operation into separate writes with intermediate files. This is
safer than guessing ExifTool command-order behavior:

```sh
exifmodern write --delete GPS:All --output-file step1.jpg image.jpg
exifmodern write --set XMP-dc:Title="Public copy" --output-file final.jpg step1.jpg
```

### I need ExifTool-compatible behavior for a route ExifModern defers

Use the diagnostic code as the issue/reporting key. ExifModern's public write
surface is designed to expose unsupported route boundaries clearly so future
native writers can implement those routes without changing application-level
error handling.

## Production Checklist

Before deploying write automation:

- Run the exact write on sample files copied from production.
- Require `result.status == "ok"`.
- Log full JSON write results.
- Validate the specific tags or groups your job changes.
- Prefer `output_path` / `--output-file` until rollback behavior is proven.
- Use explicit backups before in-place writes.
- Treat preserve-time and overwrite-in-place requests as route-sensitive.
- Do not parse human text; consume structured JSON or typed Python results.
