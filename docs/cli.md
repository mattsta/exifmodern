# Command-Line Usage

`exifmodern` is the production command-line interface for reading, inspecting,
querying, and writing metadata. It is designed for two common audiences:

- People who already know ExifTool and want familiar command-line behavior.
- Python and automation users who want predictable structured output without
  shelling out to Perl.

The public command surface is:

```sh
exifmodern read          # read metadata from files or directories
exifmodern inspect       # inspect file/container structure
exifmodern write         # plan or execute supported metadata writes
exifmodern capabilities  # show implemented and deferred public surfaces
exifmodern tag-lookup    # query the bundled TagLookup catalog
exifmodern listgeo       # list the bundled geolocation database
```

Run `exifmodern --help` or `exifmodern <command> --help` to see the exact
options supported by your installed version.

## Installation Assumptions

This guide assumes `exifmodern` is already installed as a command:

```sh
exifmodern --help
```

For one-off use with `uv`, run:

```sh
uv tool run exifmodern --help
uv tool run exifmodern read photo.jpg
```

For an activated project environment, run:

```sh
uv run exifmodern --help
uv run exifmodern read photo.jpg
```

The production package includes the runtime data needed by the public commands.
Catalog commands such as `tag-lookup` and `listgeo` default to bundled package
data and do not require a source checkout.

## Quick Start

Read a single file:

```sh
exifmodern read photo.jpg
```

Read JSON for use from another program:

```sh
exifmodern read -json photo.jpg
```

Read selected tags:

```sh
exifmodern read -tag FileType -tag ImageWidth -tag DateTimeOriginal photo.jpg
```

Read a directory recursively:

```sh
exifmodern read -r photos/
```

Inspect a media container:

```sh
exifmodern inspect video.mp4
```

Check whether a write route is available before modifying files:

```sh
exifmodern capabilities --writable-tag XMP-dc:Title
exifmodern write --set XMP-dc:Title="Example title" -o edited.jpg photo.jpg
```

Look up tag names and writable diagnostics:

```sh
exifmodern tag-lookup --tag Make
exifmodern tag-lookup --writable-tag XMP-dc:Title
```

## Reading Metadata

The `read` command accepts one or more file or directory paths:

```sh
exifmodern read image.jpg
exifmodern read image.jpg sidecar.xmp video.mp4
exifmodern read photos/
```

By default, `read` renders a human-readable text listing similar to ExifTool's
standard output. Use explicit output formats for automation or interchange.

## Read Output Formats

Use `--format` or ExifTool-compatible shorthand options:

```sh
exifmodern read --format text image.jpg
exifmodern read --format json image.jpg
exifmodern read --format xml image.jpg
exifmodern read --format csv image.jpg
exifmodern read --format tab image.jpg
exifmodern read --format html image.jpg
exifmodern read --format php image.jpg
```

Equivalent ExifTool-style aliases are also accepted:

```sh
exifmodern read -json image.jpg
exifmodern read -X image.jpg
exifmodern read -csv image.jpg
exifmodern read -t image.jpg
exifmodern read -T image.jpg
exifmodern read -htmlFormat image.jpg
exifmodern read -php image.jpg
```

Use JSON when calling ExifModern from scripts:

```sh
exifmodern read -json image.jpg
```

Use CSV or tabular output for spreadsheets and shell pipelines:

```sh
exifmodern read -csv image1.jpg image2.jpg
exifmodern read -T -tag FileName -tag FileType -tag ImageWidth photos/*.jpg
```

Use XML when you need RDF/XML-style structured output:

```sh
exifmodern read -X image.jpg
```

XML can include tag ID metadata when provenance is available:

```sh
exifmodern read -X -D image.jpg
exifmodern read -X -H image.jpg
exifmodern read -X --xml-table-metadata image.jpg
```

## Text Rendering Controls

Use short-name modes to reduce text output:

```sh
exifmodern read -s image.jpg
exifmodern read -s2 image.jpg
exifmodern read -s3 image.jpg
exifmodern read -S image.jpg
```

The modes follow ExifTool-style intent:

- `-s` prints tag names instead of descriptions.
- `-s2` removes alignment padding.
- `-s3` prints values only.
- `-S` uses very-short text output with no alignment padding.

Sort output labels:

```sh
exifmodern read -sort image.jpg
```

Force requested missing tags to print:

```sh
exifmodern read -f -tag DateTimeOriginal image.jpg
```

By default, missing forced tags render with `-`, matching common ExifTool
automation behavior.

Join list values with a custom separator:

```sh
exifmodern read -sep ", " image.jpg
```

Select a specific list item:

```sh
exifmodern read -tag Keywords -listItem 0 image.jpg
```

CSV delimiter can be changed for CSV output:

```sh
exifmodern read -csv -csvDelim ";" image.jpg
```

Double quote delimiters are rejected, matching ExifTool's CSV delimiter
restriction.

## Group Names And Duplicates

ExifTool groups tags into families. ExifModern accepts the same public group
projection options for rendered output:

```sh
exifmodern read -G image.jpg
exifmodern read -G0 image.jpg
exifmodern read -G1 image.jpg
exifmodern read -G2 image.jpg
exifmodern read -G4 image.jpg
exifmodern read -G0:1 image.jpg
exifmodern read -G0:2 image.jpg
exifmodern read -G1:2 image.jpg
```

Common usage:

```sh
exifmodern read -G -s image.jpg
exifmodern read -G0:1 -a -s image.jpg
```

Use `-a` when you want duplicate tag names included instead of collapsed:

```sh
exifmodern read -a image.jpg
exifmodern read -G -a -s image.jpg
```

Use `--a` to explicitly disable duplicate tag output after an earlier duplicate
option in a generated command:

```sh
exifmodern read -a --a image.jpg
```

## Tag Selection And Exclusion

Select tags with repeated `-tag` options:

```sh
exifmodern read -tag FileName -tag FileType -tag MIMEType image.jpg
exifmodern read -tag Make -tag Model -tag LensModel image.jpg
```

Exclude tags with repeated `-x` options:

```sh
exifmodern read -x ThumbnailImage image.jpg
exifmodern read -x MakerNotes -x PreviewImage image.jpg
```

Selection and exclusion can be combined with output formats:

```sh
exifmodern read -json -tag FileName -tag FileType -tag ImageWidth image.jpg
exifmodern read -csv -tag FileName -tag FileSize -tag MIMEType photos/*.jpg
```

Use `-u` to include unknown tags that are normally suppressed:

```sh
exifmodern read -u image.jpg
```

The accepted aliases include ExifTool-style spellings such as `-unknown`,
`-Unknown`, `-UNKNOWN`, `-U`, `-unknown2`, `-Unknown2`, and `-UNKNOWN2`.

## Numeric, Binary, And Structured Values

Request numeric/raw values:

```sh
exifmodern read -n image.jpg
```

The public CLI recognizes numeric-output intent. Where a native read path has
not yet exposed raw-value rendering for a tag, ExifModern reports an explicit
diagnostic rather than silently returning a guessed value.

Return to print-converted values after numeric intent:

```sh
exifmodern read -n -printConv image.jpg
```

Suppress binary values in rendered metadata:

```sh
exifmodern read --b image.jpg
```

Request ExifTool-style binary extraction:

```sh
exifmodern read -b -tag ThumbnailImage image.jpg
```

Binary extraction is recognized as a public interface request. If a requested
binary payload is not exposed by the current native route, the command reports
an explicit unsupported diagnostic instead of emitting partial or misleading
data.

Preserve source-backed structured XMP values in XML output:

```sh
exifmodern read -X -struct image.jpg
```

## Directory Traversal

Read all directly supported files in a directory:

```sh
exifmodern read photos/
```

Recurse into subdirectories:

```sh
exifmodern read -r photos/
```

Recurse and include dot-prefixed directories:

```sh
exifmodern read -r. photos/
```

Ignore a directory name or path during scans:

```sh
exifmodern read -r -i cache photos/
exifmodern read -r -i thumbnails photos/
```

Skip hidden dot files and directories:

```sh
exifmodern read -r -i HIDDEN photos/
```

Process only specific extensions:

```sh
exifmodern read -r -ext jpg photos/
exifmodern read -r -ext jpg -ext heic -ext mov photos/
```

Exclude specific extensions:

```sh
exifmodern read -r --ext tmp photos/
exifmodern read -r --ext json --ext txt photos/
```

Add an extension to the normally scanned public read extensions:

```sh
exifmodern read -r -ext+ custom photos/
```

Extension matching is intended for directory traversal. If you pass a file path
directly, ExifModern attempts to process that file path directly.

## Charset And Language Controls

Use Windows Latin-1/cp1252 output rendering:

```sh
exifmodern read -L image.jpg
```

Choose an output charset explicitly:

```sh
exifmodern read -charset latin image.jpg
exifmodern read -charset utf8 image.jpg
exifmodern read -charset filename=utf8 image.jpg
```

Apply packaged language translations to safe public read labels:

```sh
exifmodern read -lang fr image.jpg
exifmodern read -lang de image.jpg
```

Language availability depends on packaged runtime data. Unsupported language
or charset requests should produce explicit diagnostics instead of changing
output unpredictably.

## API Options And User Parameters

ExifModern recognizes ExifTool-style API options in the public read parser:

```sh
exifmodern read -api LargeFileSupport=1 image.jpg
```

Generic API effects that are not connected to a native public route are
reported as diagnostics. This is intentional: scripts can detect that an option
was understood but not executed, instead of receiving silent no-op behavior.

User parameters are also parsed:

```sh
exifmodern read -userParam Example=Value image.jpg
```

User-parameter interpolation is reported as a public blocker where the native
route does not support it.

## Config Files And Plug-Ins

ExifModern recognizes ExifTool compatibility options for config files and
plug-ins:

```sh
exifmodern read -config custom.config image.jpg
exifmodern read -use SomeModule image.jpg
```

The production command does not load arbitrary Perl code or arbitrary plug-in
modules. These options return explicit public blockers. This keeps the
production runtime deterministic, packageable, and safe for Python
applications.

## Low-Latency Local Client

For repeated process-style calls, ExifModern can run a persistent localhost
backend:

```sh
exifmodern server --host 127.0.0.1 --port 8765
```

The server prints one startup JSON line containing the bound protocol, host,
and port. It accepts bounded newline-delimited JSON requests and routes each
request through the normal public CLI implementation in the already-running
Python process.

`exifc` is the optional Rust client for this backend:

```sh
exifc --host 127.0.0.1 --port 8765 -- read --format json photo.jpg
exifc --host 127.0.0.1 --port 8765 -- write --delete GPS:all -o no-gps.jpg photo.jpg
```

Build `exifc` from a source checkout:

```sh
cargo build --release --manifest-path tools/exifmodern_rust_client/Cargo.toml
install -m 0755 tools/exifmodern_rust_client/target/release/exifc ~/.local/bin/exifc
```

Use the Python API for Python applications that can import `exifmodern`
directly. Use `exifc` when an external local process wants CLI-compatible
requests without paying Python startup cost for every command.

## Diagnostics And Deferred Behavior

Some ExifTool-compatible options are accepted by the parser because users and
automation tools commonly pass them, but the current public runtime may report
a typed diagnostic instead of executing the behavior.

Examples include:

```sh
exifmodern read -htmlDump image.jpg
exifmodern read -v image.jpg
exifmodern read -v2 image.jpg
exifmodern read -ee image.jpg
exifmodern read -ee2 image.jpg
exifmodern read -scanForXMP image.jpg
```

Output-routing options are also parsed and represented as public intent:

```sh
exifmodern read -w txt image.jpg
exifmodern read -W "%d%f_%t%-c.%s" image.jpg
exifmodern read -Wext jpg image.jpg
exifmodern read -o output.jpg image.jpg
```

When a route is deferred, ExifModern should make that visible. The important
contract is that unsupported behavior is explicit and machine-detectable rather
than silently ignored.

For automation, prefer JSON:

```sh
exifmodern read -json image.jpg
exifmodern capabilities --format json
```

Then check both the process exit status and any diagnostic records.

## Inspecting Files

Use `inspect` when you want structure-level information rather than the normal
rendered metadata listing:

```sh
exifmodern inspect image.jpg
exifmodern inspect video.mp4
exifmodern inspect image.jpg video.mp4 sidecar.xmp
```

Inspection is useful when:

- A file is recognized but only high-level metadata is rendered.
- You want to understand container structure before writing metadata.
- You are comparing image, video, and sidecar behavior.
- You need a diagnostic view without changing the normal read output.

`inspect` accepts file paths only. It does not expose the broader `read`
formatting and traversal options.

## Writing Metadata

Use `write` to set or delete supported metadata tags:

```sh
exifmodern write --set XMP-dc:Title="Example title" -o edited.jpg photo.jpg
exifmodern write --delete GPS:all -o no-gps.jpg photo.jpg
```

Multiple set and delete requests may be passed together:

```sh
exifmodern write \
  --set XMP-dc:Title="Launch image" \
  --set XMP-dc:Description="Public campaign asset" \
  --delete GPS:all \
  -o edited.jpg \
  photo.jpg
```

Write to a new output file:

```sh
exifmodern write --set XMP-dc:Title="Example" -o edited.jpg photo.jpg
```

Request replacement of the original file:

```sh
exifmodern write --set XMP-dc:Title="Example" --overwrite-original photo.jpg
```

Request ExifTool `overwrite_original_in_place` semantics:

```sh
exifmodern write --set XMP-dc:Title="Example" --overwrite-original-in-place photo.jpg
```

If in-place attribute preservation is not supported for the selected route, the
command reports a source-backed blocker rather than pretending to preserve all
filesystem attributes.

Preserve filesystem modification time on supported write routes:

```sh
exifmodern write --set XMP-dc:Title="Example" -P -o edited.jpg photo.jpg
```

Split list writes using a custom separator:

```sh
exifmodern write --set XMP-dc:Subject="one, two, three" -sep ", " -o edited.jpg photo.jpg
```

Add writable-selection diagnostics from a generated TagLookup package:

```sh
exifmodern write \
  --tag-lookup-package /path/to/generated-index-package \
  --set XMP-dc:Title="Example" \
  -o edited.jpg \
  photo.jpg
```

Most users should not need `--tag-lookup-package`; the public package includes
bundled runtime data for normal catalog queries.

## Checking Capabilities

Use `capabilities` before relying on a specific format, tag, or write route in
automation.

Human-readable report:

```sh
exifmodern capabilities --format text
```

Structured JSON report:

```sh
exifmodern capabilities --format json
```

Include experimental surfaces:

```sh
exifmodern capabilities --include-experimental
```

Query tag capability details:

```sh
exifmodern capabilities --tag Make
exifmodern capabilities --tag "GPS*"
```

Query writable tag diagnostics:

```sh
exifmodern capabilities --writable-tag XMP-dc:Title
exifmodern capabilities --writable-tag GPSLatitude
```

The command defaults to bundled generated-index data. `--tag-lookup-package`
is available for advanced deployments that intentionally use a different
generated catalog package.

## Querying The Tag Catalog

Use `tag-lookup` to resolve public tag names and wildcard searches through the
bundled TagLookup catalog:

```sh
exifmodern tag-lookup --tag Make
exifmodern tag-lookup --tag Model
exifmodern tag-lookup --tag "GPS*"
```

Query writable-selection diagnostics:

```sh
exifmodern tag-lookup --writable-tag XMP-dc:Title
exifmodern tag-lookup --writable-tag GPSLatitude
```

Query multiple tags in one command:

```sh
exifmodern tag-lookup --tag Make --tag Model --writable-tag XMP-dc:Title
```

Use an explicit generated-index package only if you are intentionally running
against a custom packaged catalog:

```sh
exifmodern tag-lookup \
  --tag-lookup-package /path/to/generated-index-package \
  --tag Make
```

## Listing Geolocation Data

Emit ExifTool-compatible `-listgeo` CSV-style text:

```sh
exifmodern listgeo
```

Sort by city:

```sh
exifmodern listgeo -sort
```

Emit structured JSON:

```sh
exifmodern listgeo --json
```

Apply packaged language translations when available:

```sh
exifmodern listgeo -lang fr
```

Use supported geolocation API filters:

```sh
exifmodern listgeo -api GeolocMinPop=100000
exifmodern listgeo -api GeolocFeature=PPL
exifmodern listgeo -api GeolocAltNames=1
```

Use multiple API filters together:

```sh
exifmodern listgeo -sort -api GeolocMinPop=100000 -api GeolocFeature=PPL
```

The supported public geolocation API option names are:

- `GeolocFeature`
- `GeolocMinPop`
- `GeolocAltNames`

The command uses bundled geolocation data by default. Use
`--geolocation-package` only for an intentionally supplied generated package:

```sh
exifmodern listgeo --geolocation-package /path/to/geolocation-package --json
```

## Automation Tips

Prefer JSON for programmatic reads:

```sh
exifmodern read -json image.jpg
```

Prefer `capabilities --format json` before depending on a feature in a large
pipeline:

```sh
exifmodern capabilities --format json
```

Select only the tags you need for faster and smaller output:

```sh
exifmodern read -json -tag FileName -tag FileType -tag ImageWidth image.jpg
```

Use explicit directory traversal filters:

```sh
exifmodern read -json -r -ext jpg -ext heic -i HIDDEN photos/
```

Use output files for writes when building a safe workflow:

```sh
exifmodern write --delete GPS:all -o sanitized.jpg original.jpg
```

Only switch to `--overwrite-original` after validating the route on sample
files:

```sh
exifmodern write --delete GPS:all --overwrite-original original.jpg
```

Check diagnostics rather than assuming every ExifTool-compatible option is
fully executable:

```sh
exifmodern read -json -ee video.mp4
```

For Python applications, prefer the Python-native API when you do not need a
subprocess boundary. The CLI remains useful for shell scripts, user-facing
tools, and ExifTool-compatible command invocations.

## Troubleshooting

Check the command exists:

```sh
exifmodern --help
```

Check command-specific syntax:

```sh
exifmodern read --help
exifmodern write --help
exifmodern capabilities --help
```

If a tag does not appear, try selecting it directly and forcing missing output:

```sh
exifmodern read -f -tag DateTimeOriginal image.jpg
```

If duplicate names are being collapsed, allow duplicates and include groups:

```sh
exifmodern read -G -a -s image.jpg
```

If a directory scan misses files, add recursion and explicit extensions:

```sh
exifmodern read -r -ext jpg -ext jpeg -ext heic photos/
```

If hidden files are unexpectedly included or excluded, choose the traversal
mode explicitly:

```sh
exifmodern read -r photos/
exifmodern read -r. photos/
exifmodern read -r -i HIDDEN photos/
```

If a write does not execute, check the writable tag and route:

```sh
exifmodern capabilities --writable-tag XMP-dc:Title
exifmodern tag-lookup --writable-tag XMP-dc:Title
```

If you see a diagnostic for a deferred feature, the option was recognized but
the native public implementation did not execute that behavior. Use
`capabilities` to check current support, or remove the deferred option from
automation until that route is available.

If output encoding is wrong for your terminal or downstream program, set the
charset explicitly:

```sh
exifmodern read -charset utf8 image.jpg
exifmodern read -L image.jpg
```

If a catalog command cannot find data, make sure you are running the installed
production package rather than a partially copied source tree:

```sh
exifmodern tag-lookup --tag Make
exifmodern listgeo --json
```

## Public CLI Contract

The public CLI is intentionally explicit about unsupported or deferred
behavior. A command may:

- Produce metadata or catalog output.
- Produce a structured diagnostic for a recognized but deferred option.
- Fail with a clear parser or runtime error for invalid input.

It should not silently pretend that unsupported ExifTool behavior succeeded.
For production automation, treat diagnostics as part of the command contract
and prefer structured output where available.
