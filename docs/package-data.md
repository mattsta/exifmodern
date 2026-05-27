# Bundled Package Data

ExifModern ships production runtime catalogs inside the Python package. A
normal install, wheel install, or `uv tool run exifmodern` invocation should be
usable without a source checkout, without a separate data download, and without
access to maintainer-only repository files.

This guide explains what data is bundled, how it is located at runtime, how to
verify deployments, and what to check when package data is missing or slow to
load.

## What Is Bundled

The public package includes sharded runtime resources under `exifmodern.data`:

| Resource                                                                                 | Public purpose                                                                                                           |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `runtime-data-manifest.json`                                                             | Top-level manifest listing the runtime data families.                                                                    |
| `generated-index/manifest.json`, compact JSON shards, and matching `.pickle` sidecars    | Tag lookup, list/catalog, file-type, group-family, and lens-identity shards.                                             |
| `generated-index/geolocation.pickle` and `generated-index/geolocation.repository.pickle` | GeoNames-backed geolocation shard plus the pre-materialized typed lookup repository used by geolocation-only code paths. |
| `makernote/manifest.json`, `makernote/*.json`, and matching `.pickle` sidecars           | One maker-note shard per ExifTool maker-note module.                                                                     |
| `charset-language/manifest.json` and per-language/per-charset `.pickle` shards           | Per-language translation shards and per-charset mapping shards.                                                          |

In source-maintainer checkouts, `.json.gz`, `.pickle`, and `.pickle.gz`
runtime-data files are generated artifacts and are ignored. In the generated
public release tree and production wheel, `.pickle` sidecars are included
intentionally as installed runtime assets and `.json.gz` source shards are
excluded. Public users should receive a complete package that does not require
regeneration scripts, GeoNames downloads, or external comparison tooling.

These files are installed as package resources, not as user configuration files.
They are part of the runtime application.

## Runtime Data Architecture

ExifModern uses a manifest-first runtime-data layout. The top-level manifest
names the available data families; each family manifest names the shards inside
that family; public runtime services load only the shard required by the
selected operation.

```text
exifmodern.data/
  runtime-data-manifest.json
    generated_index -> generated-index/manifest.json
    makernote -> makernote/manifest.json
    charset_language -> charset-language/manifest.json

  generated-index/
    manifest.json
    tag_lookup.json
    tag_lookup.pickle
    geolocation.pickle
    geolocation.repository.pickle
    listx_catalog.json
    listx_catalog.pickle
    file_type_catalog.json
    file_type_catalog.pickle
    group_family_catalog.json
    group_family_catalog.pickle
    lens_identity.json
    lens_identity.pickle

  makernote/
    manifest.json
    canon.json
    nikon.json
    sony.json
    ...

  charset-language/
    manifest.json
    charsets/
      latin.pickle
      shiftjis.pickle
      ...
    languages/
      fr.pickle
      ja.pickle
      ...
```

Lookup flow:

```text
public command / Python API call
  -> exifmodern.package_resources resolves installed package resource paths
  -> family service checks the family manifest path
  -> service selects one shard by operation-specific key
  -> geolocation requests use the pre-materialized repository pickle directly
  -> fresh pickle sidecar is used when present and current
  -> otherwise JSON or JSON.GZ payload is parsed when a source artifact is bundled
  -> service-level lookup indexes are built and cached by normal Python objects
```

Artifact policy:

- Plain JSON shards remain the readable, deterministic production source
  artifact where they are compact enough to ship directly.
- JSON.GZ shards remain source-build artifacts and are excluded from the
  public production package when a matching `.pickle` shard is shipped.
- `.pickle` sidecars are runtime accelerators generated from the same shard
  payload. They are used when the sidecar is present and the source artifact is
  not more than 30 seconds newer.
- `geolocation.repository.pickle` is a second-stage runtime artifact generated
  from the GeoNames-shaped geolocation shard. It stores the typed lookup
  repository that listgeo/geotag/geolocation operations need, so production
  users do not pay that index-construction cost at first query.
- `.pickle.gz` is a supported runtime fallback for size-constrained release
  experiments. It is profiled by the release tooling, but the default public
  package currently prefers plain pickle sidecars because they have lower load
  latency on the measured shards.
- Release decisions are made with
  `scripts/profile-runtime-data-artifacts.py`, which profiles source parse,
  plain pickle, compressed pickle read/decompress/load, compressed pickle
  streaming load, and the preferred runtime path for every shard manifest
  entry.

Current release profile, generated with:

```sh
uv run python scripts/profile-runtime-data-artifacts.py \
  --data-root src/exifmodern/data \
  --iterations 2 \
  --warmups 1 \
  --output artifacts/runtime-data-profile/runtime-data-artifact-profile.json
```

| Measurement                              | Result                                                                                                                                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Shards profiled                          | 72                                                                                                                                                                                                     |
| Families profiled                        | 51 charset/language shards, 6 generated-index shards, 15 maker-note shards                                                                                                                             |
| Source artifact bytes                    | 30.97 MB                                                                                                                                                                                               |
| Plain pickle sidecar bytes               | 41.41 MB                                                                                                                                                                                               |
| Pre-materialized geolocation repository  | 29.80 MB additional public runtime pickle; loaded only by geolocation/listgeo/geotag paths                                                                                                             |
| Compressed pickle profile-artifact bytes | 7.43 MB                                                                                                                                                                                                |
| Fastest measured loader                  | Plain pickle for most shards; source parse wins only for tiny shards                                                                                                                                   |
| Release recommendation                   | Keep compact readable JSON plus plain pickle sidecars as the default public package; exclude JSON.GZ from public release artifacts; reserve `.pickle.gz` for future size-constrained release profiles. |

The important design point is that "where is the data installed?" and "which
catalog do I need?" are separate decisions. `importlib.resources` handles the
installed wheel/source/zip location. ExifModern's family services decide which
shard to load.

### Family Split Rationale

| Family            | Split key                                                                                                              | Why this split exists                                                                                                                                         |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Generated indexes | Catalog purpose: tag lookup, geolocation, list/catalog output, file type catalog, group family catalog, lens identity. | These catalogs serve different commands. A tag lookup should not load 116,054 geolocation rows; a geolocation query should not load the full TagLookup table. |
| Maker notes       | ExifTool maker-note module/vendor: Canon, Nikon, Sony, Olympus, Panasonic, and so on.                                  | Maker-note lookups are naturally vendor-scoped. Nikon code should not need to parse Canon, Sony, and Panasonic tables first.                                  |
| Charset/language  | One shard per charset or language; public packages ship the pickle form.                                               | Most runs use no language override or one language. A French translation lookup should not inflate every other language table.                                |

Current package summary for the generated public data:

| Data family       | Current public package shape                                                                                                             |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Generated indexes | 6 shards: tag lookup, geolocation, listx catalog, file type catalog, group family catalog, lens identity.                                |
| Geolocation shard | 116,054 GeoNames city rows and feature codes filtered to match ExifTool geolocation behavior, plus a pre-materialized repository pickle. |
| Maker notes       | 15 vendor/module shards, 696 tables, 11,593 tag entries.                                                                                 |
| Charset/language  | 33 charset shards and 18 language shards, stored as deterministic gzip-compressed JSON.                                                  |

### Cache Boundaries

ExifModern has two cache layers:

- Resource path cache: `exifmodern.package_resources` caches resolved
  `importlib.resources.as_file()` paths for the process lifetime.
- Runtime repository cache: services build typed repositories or lookup indexes
  after parsing the relevant shard. Long-running applications should reuse the
  process and objects instead of repeatedly spawning a new CLI process for every
  catalog query.

The production package does not ship source-build monoliths such as
`generated-index-package.json`, `makernote-package.json`, or
`charset-language-package.json`. Those are source-build inputs used to
materialize the production shards, not public runtime resources.

## Geolocation Data Provenance

The geolocation catalog is upstream ExifTool functionality, not an
ExifModern-only convenience database.

ExifTool includes:

- `lib/Image/ExifTool/Geolocation.pm`, which implements geolocation lookup,
  nearest-city resolution, list output, and write-only geolocation behavior.
- `lib/Image/ExifTool/Geolocation.dat`, the packed city database loaded by
  `Geolocation.pm`.
- `build_geolocation`, the upstream builder that creates `Geolocation.dat`
  from GeoNames source data.
- `t/Geolocation.t` and `t/Geolocation_*.out`, the upstream test coverage.
- Public options such as `Geolocation`, `GeolocAltNames`, `GeolocFeature`,
  `GeolocMinPop`, and `GeolocMaxDist`.

ExifModern ports that behavior into typed Python services and ships the parsed
database as `generated-index/geolocation.pickle` plus the ready-to-query
`generated-index/geolocation.repository.pickle`. The public command
`exifmodern listgeo` and the Python geolocation runtime use those package
resources instead of requiring Perl or `Geolocation.dat` at runtime.

The distinction is:

- Compatibility reference: ExifTool's `Geolocation.pm`, `build_geolocation`,
  and tests define the behavior ExifModern matches.
- Data source: upstream GeoNames dumps fetched into the maintainer build cache
  with `exifmodern-dev geonames-fetch`.
- ExifModern production representation: a typed, sharded runtime catalog loaded
  through `importlib.resources`; public packages ship the `.pickle` runtime
  artifact for compressed-source shards and a pre-materialized geolocation
  repository pickle.
- ExifModern convenience surface: Python API and CLI wrappers that expose the
  package-backed geolocation runtime without requiring callers to shell out to
  Perl ExifTool.

### How Geolocation Updates Flow Into ExifModern

ExifModern treats ExifTool as the geolocation behavior reference and GeoNames
as the data source. During maintainer data-package regeneration, ExifModern
first fetches GeoNames source dumps with `exifmodern-dev geonames-fetch`, then
builds the packaged geolocation shard from that cache.

Then it writes the public package shard:

```text
src/exifmodern/data/generated-index/geolocation.pickle
src/exifmodern/data/generated-index/geolocation.repository.pickle
```

The public runtime never fetches GeoNames and never shells out to ExifTool.
Network access is a build-time operation only.

Operationally, geolocation updates happen through one of these paths:

- Behavior path: update the ExifTool reference checkout, audit `Geolocation.pm`,
  `build_geolocation`, and upstream tests, then update the Python port if
  behavior changed.
- Data path: run `exifmodern-dev geonames-fetch --output-root artifacts/geonames`,
  then regenerate ExifModern data packages with
  `exifmodern-dev database-packages --geonames-root artifacts/geonames`.

`geonames-fetch` is incremental. For each required upstream artifact it checks
GeoNames HTTP metadata before downloading:

```text
https://download.geonames.org/export/dump/allCountries.zip
https://download.geonames.org/export/dump/alternateNamesV2.zip
https://download.geonames.org/export/dump/countryInfo.txt
https://download.geonames.org/export/dump/admin1CodesASCII.txt
https://download.geonames.org/export/dump/admin2Codes.txt
https://download.geonames.org/export/dump/featureCodes_en.txt
```

The GeoNames download server exposes `Last-Modified`, `ETag`, and
`Content-Length` for these files. ExifModern sends conditional `HEAD` requests
using stored `ETag` and `Last-Modified` values; `304 Not Modified` means the
local source file can be reused. ExifModern records those fields in
`artifacts/geonames/manifest.json` as `remote_http_status`,
`remote_last_modified`, `remote_etag`, and `remote_content_length`, along with
`checked_at`, `fetched_at`, `fetch_status`, `bytes`, and `sha256`. A later fetch
reuses an existing local file when the remote metadata is unchanged; pass
`--force` to intentionally redownload all source files.

This keeps ExifModern aligned to ExifTool behavior without making ExifTool's
packed data file the production data source. The production wheel ships the
resulting pickle shard and repository pickle, not the GeoNames source
downloads, JSON.GZ source-build artifact, or Perl builder.

Geolocation is also lazy by operation. Normal `import exifmodern`,
`exifmodern --help`, public API model import, and ordinary metadata reads do
not import the geolocation runtime and do not load the GeoNames repository. The
repository is resolved only when a geolocation/listgeo/geotag code path
requests it, then it is cached for the process.

## Resource Loading Model

ExifModern uses Python's `importlib.resources` API through
`exifmodern.package_resources`. The public helpers are:

```python
from exifmodern.package_resources import (
    charset_language_package_path,
    generated_index_package_path,
    maker_note_package_path,
)
```

The family helpers return `pathlib.Path` values for bundled runtime manifests.
Shard-specific loaders resolve data shards only when the selected operation
needs them. A returned path may be a normal file inside a source tree, a file
inside an installed wheel, or a temporary extraction path managed by
`importlib.resources.as_file()`.

Important behavior:

- Treat returned paths as read-only.
- Do not store those paths in long-lived external config.
- Do not modify files under `exifmodern.data`.
- Do not assume resources live next to the current working directory.
- Do not require `../exiftool`, a maintainer checkout, or hidden artifacts for
  public runtime commands.

The helper module caches resolved resource paths for the life of the process, so
repeated catalog commands in one process should not repeatedly resolve the same
package resource.

Path resolution and JSON parsing are separate operations:

- Resolving a resource path tells ExifModern where installed package data lives.
- Loading a runtime repository parses JSON and builds typed lookup structures.
- Basic import, help, and simple read paths should avoid parsing catalog data
  unless the selected operation requires it.
- Catalog-oriented commands such as `tag-lookup`, `listgeo`, and broad
  capability queries may load the catalog they query.

ExifModern production wheels use sharded resources. A maker-note lookup for
Nikon data loads the Nikon shard, a TagLookup query loads the tag lookup shard,
a geolocation query loads the geolocation shard, and `-lang fr` loads the
French language shard instead of all charset/language data.

## Public Commands That Use Package Data

The public CLI uses bundled resources by default. Users normally do not need to
pass explicit package paths.

### Tag Lookup

Use `tag-lookup` to query the generated tag catalog:

```sh
exifmodern tag-lookup --tag Make
exifmodern tag-lookup --tag Model
exifmodern tag-lookup --tag "GPS*"
exifmodern tag-lookup --writable-tag XMP-dc:Title
```

Typical uses:

- Confirm whether a tag name is recognized.
- Check writable tag candidates before building write requests.
- Inspect wildcard matches for groups of tags.
- Validate package-backed catalog access in installed environments.

### Geolocation Catalog

Use `listgeo` to emit the bundled geolocation database in the public
ExifTool-compatible shape:

```sh
exifmodern listgeo
exifmodern listgeo --json
exifmodern listgeo -sort
exifmodern listgeo -lang en
exifmodern listgeo -api GeolocMinPop=100000
```

Common filters include:

```sh
exifmodern listgeo -api GeolocFeature=PPL
exifmodern listgeo -api GeolocCountry=US
exifmodern listgeo -api GeolocMinPop=500000
```

Use JSON output when another program needs to consume the result:

```sh
exifmodern listgeo --json
```

### Capability Queries

Use `capabilities` to check public runtime support:

```sh
exifmodern capabilities --format text
exifmodern capabilities --format json
exifmodern capabilities --tag Make
exifmodern capabilities --writable-tag XMP-dc:Title
```

Capability queries are useful in deployment smoke tests because they exercise
public API wiring and package-backed catalog lookup without requiring a media
fixture.

## Python API Smoke Tests

Use these checks when validating a package install, container image, or `uv tool`
deployment.

### Resource Presence

```python
from exifmodern.package_resources import (
    charset_language_package_path,
    generated_index_package_path,
    maker_note_package_path,
)

resources = (
    generated_index_package_path(),
    maker_note_package_path(),
    charset_language_package_path(),
)

for path in resources:
    assert path.exists(), path
    assert path.is_file(), path
    assert path.stat().st_size > 0, path
```

### Public Import And Read Surface

```python
import exifmodern

image = exifmodern.from_bytes(b"\xff\xd8\xff\xd9", name="empty.jpg")
result = image.read()

assert result.file_name == "empty.jpg"
```

This verifies that the public package can be imported and that in-memory input
can reach the public read API. Use real fixture data for deployment-level image
coverage.

### CLI Smoke Test

```sh
exifmodern --help
exifmodern capabilities --format json
exifmodern tag-lookup --tag Make
exifmodern listgeo --json
```

For automated deployment checks, run the commands above in the same environment
that will execute production workloads. That catches missing package data,
incorrect entry points, and packaging systems that omitted resource files.

## `uv tool` Deployment

ExifModern is intended to run as an installed command:

```sh
uv tool run exifmodern --help
uv tool run exifmodern capabilities --format text
uv tool run exifmodern tag-lookup --tag Make
```

When using a local wheel:

```sh
uv tool run --from ./dist/exifmodern-0.1.0-py3-none-any.whl exifmodern --help
uv tool run --from ./dist/exifmodern-0.1.0-py3-none-any.whl exifmodern tag-lookup --tag Make
```

When using a local source checkout for packaging verification:

```sh
uv tool run --from . exifmodern --help
uv tool run --from . exifmodern listgeo --json
```

If a `uv tool` install can import the package but catalog commands fail, the
most likely issue is that package data was not included in the wheel or source
distribution.

## Wheel And Container Deployment

Package data must be included when building wheels and container images.

Recommended deployment checks:

1. Build the wheel.
2. Install or run the wheel in a clean environment.
3. Run `exifmodern --help`.
4. Run `exifmodern tag-lookup --tag Make`.
5. Run `exifmodern listgeo --json`.
6. Run a minimal Python resource presence smoke test.
7. Run one representative media-file read for your workload.

Container-specific notes:

- The runtime filesystem may be read-only. That is supported for bundled data.
- Do not mount over the package directory unless you also include
  `exifmodern.data`.
- Do not strip `exifmodern/data` package resources when minimizing image size.
- If the image uses zip imports or a non-standard installer, verify
  `importlib.resources.as_file()` can materialize resource paths.

## Read-Only Resources

Bundled resources are not user-editable databases. They are versioned with the
ExifModern package and should be updated by upgrading ExifModern.

Do this:

```python
from exifmodern.package_resources import generated_index_package_path

path = generated_index_package_path()
with path.open("rb") as handle:
    header = handle.read(64)
```

Do not do this:

```python
from exifmodern.package_resources import generated_index_package_path

generated_index_package_path().write_text("custom data")
```

If an application needs custom metadata policy, keep that policy in application
configuration and pass normal public API options. Do not patch the bundled
catalog files in place.

## Explicit Package Path Overrides

Some command paths accept options such as `--tag-lookup-package` or
`--tag-lookup-package-path`. These are overrides for advanced packaging,
testing, and controlled deployment scenarios.

Normal users should not need them:

```sh
exifmodern tag-lookup --tag Make
```

Use an override only when you intentionally want to point a command at a
specific compatible package file:

```sh
exifmodern tag-lookup \
  --tag-lookup-package /opt/exifmodern/generated-index/manifest.json \
  --tag Make
```

Override files must match the schema expected by the installed ExifModern
version. Mixing package data from one version with runtime code from another
version is unsupported unless the release notes explicitly say the schema is
compatible.

## Troubleshooting

### `FileNotFoundError` For A JSON Package

Likely causes:

- The wheel was built without package data.
- A downstream repackager excluded `src/exifmodern/data/*.json`.
- A container image copied only Python files and omitted data files.
- A local editable/source install is pointing at an incomplete checkout.

Checks:

```sh
exifmodern package-data --format text
```

The command should show existing paths for the generated-index, maker-note, and
charset/language manifests plus the runtime sidecars bundled with the wheel.

### CLI Works, But Catalog Commands Fail

Run:

```sh
exifmodern capabilities --format json
exifmodern tag-lookup --tag Make
exifmodern listgeo --json
```

If `--help` works but these fail, the entry point is installed but package data
or resource loading is broken.

### Works From Source, Fails From Wheel

This usually means the source tree has data files but the wheel did not include
the required public resources. Inspect the wheel contents:

```sh
python -m zipfile -l dist/exifmodern-*.whl | grep 'exifmodern/data'
```

The wheel should contain:

```text
exifmodern/data/runtime-data-manifest.json
exifmodern/data/runtime-data-manifest.pickle
exifmodern/data/generated-index/manifest.json
exifmodern/data/generated-index/geolocation.pickle
exifmodern/data/generated-index/geolocation.repository.pickle
exifmodern/data/makernote/manifest.json
exifmodern/data/charset-language/manifest.json
```

### Works Locally, Fails In A Container

Check that the package directory in the container contains `exifmodern.data` and
that the runtime user can read installed package files:

```sh
exifmodern package-data --format json
```

### Slow Startup Or High Memory Use

Package resource path resolution should be cheap. Parsing a large catalog can be
more expensive than locating it. If a workload only reads one image, it should
not need to eagerly parse every catalog unless the requested operation requires
that catalog.

Practical guidance:

- Use `exifmodern read FILE` for normal metadata extraction.
- Use `tag-lookup`, `listgeo`, and broad capability queries only when you need
  catalog-level information.
- Keep long-running services alive rather than spawning a new process for every
  single catalog query.
- If you build a server around ExifModern, initialize expensive catalogs once
  and reuse the process.
- If basic `exifmodern --help` is slow, that is a packaging/runtime issue and
  should be reported.
- If a specific catalog command is slow, include the command, package version,
  data file sizes, and platform details in the report.

## Performance Considerations

Bundled runtime data is intentionally versioned with the package so public
runtime behavior is reproducible. Some catalogs are large because they include
generated lookup data for broad ExifTool-compatible metadata surfaces.

Expected behavior:

- Importing `exifmodern` should not require parsing every catalog.
- `exifmodern --help` should not require reading large JSON packages.
- Catalog commands may load the catalog they query.
- Maker-note data should be needed when maker-note lookup paths are exercised.
- Geolocation listing requires the generated geolocation catalog.
- Focused operations load the relevant shard rather than a source-build
  monolith. The source-build monoliths are source inputs for shard generation,
  not production package resources.

For application developers:

- Prefer the Python API for repeated operations in one process.
- Avoid launching a separate process for each file if processing large batches.
- Reuse an application process for repeated catalog lookups.
- Do not copy package JSON into temporary files unless a deployment constraint
  requires it.
- Do not mutate bundled resources to "cache" computed results.

## Deployment Checklist

Before publishing or deploying an ExifModern package, verify:

- The wheel or source distribution includes required `exifmodern/data` JSON and
  pickle package resources.
- `exifmodern --help` works in a clean environment.
- `exifmodern capabilities --format json` works.
- `exifmodern tag-lookup --tag Make` returns a successful result.
- `exifmodern listgeo --json` returns package-backed geolocation output.
- Python can import `exifmodern`.
- Python can resolve all three package resource paths.
- The deployment does not require a maintainer source checkout.
- The deployment works from a read-only package installation.
- Representative read/write operations for your application pass.

## Minimal End-To-End Verification Script

Save this as part of your deployment smoke checks if you need a single Python
probe:

```python
import exifmodern
from exifmodern.package_resources import (
    charset_language_package_path,
    generated_index_package_path,
    maker_note_package_path,
)

for path in (
    generated_index_package_path(),
    maker_note_package_path(),
    charset_language_package_path(),
):
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty package resource: {path}")

image = exifmodern.from_bytes(b"\xff\xd8\xff\xd9", name="smoke.jpg")
result = image.read()

if result.file_name != "smoke.jpg":
    raise SystemExit("public read API smoke test failed")

print("ExifModern package data smoke test passed")
```

Run it in the target environment:

```sh
python smoke_exifmodern_package_data.py
```
