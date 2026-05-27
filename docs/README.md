# ExifModern Public Documentation

This is the user-facing documentation shipped with the public release branch.
It covers installed command-line usage, Python integration, write behavior,
bundled runtime data, and the public release model.

Source-maintainer comparison tools, release build queues, and test
infrastructure are intentionally not included in public release branches.

## Start Here

- `cli.md`: command-line usage, output formats, directory traversal, catalog
  queries, diagnostics, and ExifTool-compatible option mapping.
- `python-native-api.md`: file reads, in-memory bytes, batch reads,
  ExifTool-style argument parsing, diagnostics, and typed request/result APIs.
- `write-workflows.md`: immediate writes, staged edits, in-place behavior,
  output routing, delete semantics, and safety expectations.
- `package-data.md`: bundled metadata databases, package-resource behavior,
  catalog commands, and deployment notes.
- `performance.md`: reusable ExifTool-vs-ExifModern latency benchmark utility,
  current local snapshot, low-latency local client notes, and release benchmark
  practice.
- `release-model.md`: what is included in the public branch and how public
  snapshots are produced.

## Quick Smoke Test

After installing, these commands should work without a source checkout:

```sh
exifmodern --help
exifmodern capabilities --format text
exifmodern tag-lookup --tag Make
exifmodern listgeo --json
```

For file reads:

```sh
exifmodern read image.jpg
exifmodern read --format json image.jpg
exifmodern read -G -a -s image.jpg
```

For Python:

```python
import exifmodern

image = exifmodern.open_file("image.jpg")
print(image.status)
print(image.value("FileType"))
```
