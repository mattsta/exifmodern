# Public Release Model

ExifModern public releases are clean source snapshots generated from the
installable package boundary. The public branch is intended for users,
packagers, and application authors who want the runtime CLI, Python API,
bundled data, and documentation without maintainer workflow files.

## Included In Public Releases

- `src/exifmodern/`: production runtime package.
- Public `exifmodern` CLI entry point and Python-native API.
- Bundled runtime lookup data, including compact JSON shards, generated
  `.pickle` sidecars, and pre-materialized lookup repositories used by
  installed packages for fast startup and lazy catalog loading.
- Public user documentation under `docs/`.
- Production `pyproject.toml`, `.python-version`, and optional lockfile.

## Excluded From Public Releases

- Test suites and fixtures.
- Source-maintainer comparison tools.
- Maintainer planning notes and work queues.
- Benchmark artifacts and generated reports.
- Release-generation manifests.
- Source-data fetch caches and build outputs used to produce packaged shards.
- Local virtual environments and tool caches.

## Why Snapshot Branches

The public branch is a single-purpose release view. It keeps the repository
small, readable, and focused on installation and runtime usage. Each release can
be regenerated from the package boundary, so users see the current product
surface instead of maintainer workflow history.

The generated tree should be validated before publication:

```sh
uv build --wheel
uv run --no-project --with ./dist/exifmodern-0.1.0-py3-none-any.whl exifmodern --help
uv run --no-project --with ./dist/exifmodern-0.1.0-py3-none-any.whl exifmodern --ver
uv run --no-project --with ./dist/exifmodern-0.1.0-py3-none-any.whl exifmodern package-data --format json
```

Use representative local media files for deeper read/write smoke checks. Do not
copy local fixture sets into the public branch.

## Runtime Data Artifact Policy

The public release branch includes generated `.pickle` sidecars and compact JSON
shards that the built wheel includes, because those files are runtime package
assets for users. Public releases exclude compressed source shards when a
runtime pickle is shipped.

Release contents are intentionally asymmetric with source-maintainer checkouts:

- Source view: human-maintained source plus maintainer automation.
- Public release branch: installable production package snapshot with all
  runtime data needed by `uv tool run exifmodern`.
