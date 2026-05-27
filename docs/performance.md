# Performance Benchmarks

ExifModern includes a reusable benchmark utility for comparing local ExifTool
and ExifModern command latency on the same machine:

```sh
uv run python scripts/benchmark-exiftool-vs-exifmodern.py \
  --iterations 10 \
  --warmups 3 \
  --max-files 20 \
  --path-list artifacts/benchmarks/public-benchmark-paths.txt \
  --timeout 30 \
  --output-json artifacts/benchmarks/exiftool-vs-exifmodern.json \
  --output-md artifacts/benchmarks/exiftool-vs-exifmodern.md
```

By default the utility uses:

- ExifTool: `../exiftool/exiftool`
- ExifModern: `.venv/bin/exifmodern`
- Sample file source: `TEST_FILES`, or a curated `--path-list` for release
  publishing.

The benchmark script may be launched with `uv run python`, but measured
ExifModern commands must not use `uv run`; otherwise the tables include the
`uv` wrapper cost instead of the tool latency being compared.

The current public release benchmark uses
`artifacts/benchmarks/public-benchmark-paths.txt` to cover representative
`MP4`, `JPG`, `MOV`, `PNG`, `WEBP`, `PDF`, and `RW2` paths. On another
machine, pass a local `--path-list` with equivalent representative files before
publishing new numbers.

The benchmark emits durable JSON and Markdown reports. It measures command
success, latency, and recorded output-match status for the sampled commands.
Broader capability coverage is validated by the public CLI/API and real-file
test suites.

## Report Semantics

Benchmark reports separate cold subprocess scenarios from persistent
`-stay_open` scenarios:

- Cold scenarios measure complete command invocations, including process
  startup, package imports, argument parsing, read execution, and output
  rendering.
- Persistent scenarios start one long-lived process per tool, perform warmup
  frames first, and then time only measured request/response frames sent through
  the already-running process.
- Cold and persistent matching scenarios must use the same sampled scenario/frame
  set for both tools. If a cold scenario reads a selected `TEST_FILES` path with
  specific arguments, the matching persistent frame must read that same path
  with the corresponding persistent arguments.
- Per-tool report statistics for each scenario are min, max, median, average,
  and standard deviation over the measured iterations only. Warmups are
  recorded for reproducibility but are excluded from those aggregates.
- Status fields describe benchmark command health only. `ok/ok` means both
  tools completed the measured benchmark operation; it does not prove complete
  metadata compatibility.
- Do not claim complete output matching from this benchmark unless the report also records
  comparable output status and output hashes for both tools and those values
  prove the outputs matched for the same frames.

## Measured Command Lifecycles

The benchmark compares different transport lifecycles. These labels are not
interchangeable:

### Cold CLI Subprocess

Cold CLI rows launch a new process for every measured iteration. Example text
read commands:

```sh
../exiftool/exiftool /path/to/file.jpg
.venv/bin/exifmodern read /path/to/file.jpg
```

Example JSON read commands:

```sh
../exiftool/exiftool -j /path/to/file.jpg
.venv/bin/exifmodern read --format json /path/to/file.jpg
```

This mode includes process startup, dynamic loader work, Python/Perl startup,
imports, argument parsing, metadata extraction, rendering, and process exit.

### Persistent Stdin

Persistent stdin rows launch exactly one long-lived process per tool for the
whole eligible scenario matrix, warm it up, and then reuse that same process for
all measured frames.

ExifTool process:

```sh
../exiftool/exiftool -stay_open True -@ -
```

Frame sent to that same process for a text read:

```text
/path/to/file.jpg
-execute
```

ExifModern process:

```sh
.venv/bin/exifmodern -stay_open True -@ -
```

Frame sent to that same process for a text read:

```text
read
/path/to/file.jpg
-execute
```

Frame sent to that same process for a JSON read:

```text
read
--format
json
/path/to/file.jpg
-execute
```

This is the `spawn(...); write(frame); read_until_ready(); repeat` model. It is
not a Unix socket and it is not restarted per command.

### Persistent Server TCP

Server TCP rows launch one long-lived ExifModern server, open one TCP
connection, warm it up, and reuse that same socket for all measured frames.
This column is closest to "server processing time plus JSON/TCP request and
response I/O" because it does not start a client process for every request.

Server process:

```sh
.venv/bin/exifmodern server --host 127.0.0.1 --port 0
```

Frame sent repeatedly on the same TCP connection:

```json
{ "protocol": "exifmodern-jsonl-v1", "argv": ["read", "/path/to/file.jpg"] }
```

This measures backend request latency plus local JSON/TCP framing. It does not
include `exifc` process startup.

### Server With Spawned `exifc`

Server+spawned `exifc` rows keep the same long-lived ExifModern server alive,
but intentionally launch a fresh Rust `exifc` command for every measured
request:

```sh
tools/exifmodern_rust_client/target/release/exifc \
  --host 127.0.0.1 \
  --port "$EXIFMODERN_SERVER_PORT" \
  --timeout-ms 5000 \
  -- \
  read /path/to/file.jpg
```

That column measures command-adapter latency. The `Spawned exifc overhead ms`
column is:

```text
median(server + freshly spawned exifc) - median(persistent server TCP)
```

It includes process launch, dynamic loader work, macOS code-signature
validation, Rust program startup, TCP connect, JSON encode/decode,
request/response I/O, and stdout/stderr forwarding. It is not measuring packets
traveling 100 miles; the persistent TCP column is the closer measurement of raw
local server request latency.

In short:

- `ExifModern persistent server TCP request` means one already-running server
  and one already-open client socket are reused for all measured requests.
- `ExifModern spawned exifc client request` means one already-running server is
  reused, but every measured request starts a new `exifc` process that connects,
  sends one request, reads one reply, writes output, and exits.

### Unix-Domain Socket Server

For local-only integrations, ExifModern also supports a Unix-domain socket
server:

```sh
.venv/bin/exifmodern server --unix-socket /tmp/exifmodern.sock
```

The Rust client can connect without TCP:

```sh
tools/exifmodern_rust_client/target/release/exifc \
  --unix-socket /tmp/exifmodern.sock \
  --timeout-ms 5000 \
  -- \
  read /path/to/file.jpg
```

Use `scripts/benchmark-exifc-client-overhead.py` to decompose client overhead
between baseline process launch, `exifc --help`, persistent TCP, spawned TCP
`exifc`, persistent Unix socket, and spawned Unix-socket `exifc`.

<!-- BEGIN GENERATED EXIFC OVERHEAD RESULTS: scripts/update-performance-doc.py -->

The current local overhead artifact (`artifacts/benchmarks/exifc-client-overhead.md`) reports:

| Measurement                  | Command                                                                                                            | Median / avg / stddev ms |  Min / max ms | Status  |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------ | -----------------------: | ------------: | ------- |
| `baseline_process`           | `/usr/bin/true`                                                                                                    |    1.889 / 1.907 / 0.315 | 1.411 / 3.184 | ok      |
| `exifc_help_process`         | `tools/exifmodern_rust_client/target/release/exifc --help`                                                         |    2.151 / 2.193 / 0.306 | 1.774 / 3.047 | nonzero |
| `persistent_tcp_request`     | `exifmodern-server-tcp 127.0.0.1 <port> --help`                                                                    |    0.699 / 0.770 / 0.387 | 0.631 / 3.987 | ok      |
| `spawned_exifc_request`      | `tools/exifmodern_rust_client/target/release/exifc --host 127.0.0.1 --port <port> --timeout-ms 5000 -- --help`     |    3.776 / 3.751 / 0.399 | 2.929 / 5.051 | ok      |
| `persistent_unix_request`    | `exifmodern-server-unix /tmp/exifmodern.sock --help`                                                               |    0.674 / 0.742 / 0.381 | 0.561 / 3.943 | ok      |
| `spawned_exifc_unix_request` | `tools/exifmodern_rust_client/target/release/exifc --unix-socket /tmp/exifmodern.sock --timeout-ms 5000 -- --help` |    3.734 / 3.741 / 0.452 | 2.942 / 5.502 | ok      |

## Derived Deltas

- Spawned `exifc` minus persistent TCP median: `3.077 ms`
- Spawned Unix-socket `exifc` minus persistent Unix-socket median: `3.060 ms`
- Persistent Unix socket minus persistent TCP median: `-0.025 ms`
- Spawned `exifc` minus baseline process median: `1.887 ms`

The spawned `exifc` command does not spawn ExifModern. It connects to the already-running `exifmodern server` over TCP or a Unix-domain socket, sends one JSONL request, prints the response, and exits.

<!-- END GENERATED EXIFC OVERHEAD RESULTS -->

## Generated Result Policy

Numeric benchmark results in this page are generated documentation, not
hand-maintained prose. The canonical local result files are:

- `artifacts/benchmarks/exiftool-vs-exifmodern.json`
- `artifacts/benchmarks/exiftool-vs-exifmodern.md`

The Markdown artifact is generated from a single report template inside
`scripts/benchmark-exiftool-vs-exifmodern.py`. It contains the cold subprocess,
persistent stdin, persistent server TCP, and spawned `exifc` tables for the same
scenario set. The JSON artifact contains the same measurements plus min/max,
command arguments, stdout hashes, return codes, and timeout counts.

Run `scripts/update-performance-doc.py` after regenerating the benchmark. That
script replaces the generated section below so the public docs contain current
tables without hand-maintained numeric rows.

<!-- BEGIN GENERATED BENCHMARK RESULTS: scripts/update-performance-doc.py -->

## Current Generated Benchmark Results

This section is generated from `artifacts/benchmarks/exiftool-vs-exifmodern-after-import-guards.md` by `scripts/update-performance-doc.py`.
Do not edit benchmark rows here by hand; regenerate the benchmark artifact and rerun the updater.

## Cold CLI Subprocesses

| Operation | Output         | Scope             |   ExifTool med/avg/std ms | ExifModern med/avg/std ms | Modern/Tool ratio | Status |
| --------- | -------------- | ----------------- | ------------------------: | ------------------------: | ----------------: | ------ |
| `startup` | `help/version` | `process`         |   57.824 / 57.892 / 0.876 |   16.880 / 16.845 / 0.558 |             0.292 | ok/ok  |
| `listgeo` | `json`         | `GeoNames >=100k` | 404.345 / 405.872 / 4.053 | 496.855 / 499.155 / 9.970 |             1.229 | ok/ok  |
| `read`    | `text`         | `(6.0 MiB MP4)`   |   76.369 / 76.448 / 0.910 |   84.799 / 84.816 / 1.375 |             1.110 | ok/ok  |
| `read`    | `json`         | `(6.0 MiB MP4)`   |   83.679 / 83.875 / 0.648 |   85.435 / 85.736 / 0.971 |             1.021 | ok/ok  |
| `read`    | `text`         | `(11.0 MiB JPG)`  |   85.230 / 85.088 / 1.596 | 127.401 / 127.066 / 2.561 |             1.495 | ok/ok  |
| `read`    | `json`         | `(11.0 MiB JPG)`  |   84.968 / 85.534 / 1.189 | 129.737 / 131.457 / 6.590 |             1.527 | ok/ok  |
| `read`    | `text`         | `(57.3 MiB MOV)`  | 129.204 / 129.527 / 1.511 | 104.431 / 104.596 / 1.526 |             0.808 | ok/ok  |
| `read`    | `json`         | `(57.3 MiB MOV)`  | 136.752 / 136.764 / 1.620 | 105.677 / 105.479 / 1.483 |             0.773 | ok/ok  |
| `read`    | `text`         | `(10.5 MiB JPG)`  |   85.490 / 85.419 / 1.107 | 125.413 / 125.748 / 2.220 |             1.467 | ok/ok  |
| `read`    | `json`         | `(10.5 MiB JPG)`  |   86.452 / 86.391 / 1.658 | 126.767 / 126.701 / 1.809 |             1.466 | ok/ok  |

## Representative Cold Examples By File Type

This section is selected from the measured cold-read rows, grouped by file extension, and capped at two highest-impact rows per file type. Impact is ranked by ExifModern-vs-ExifTool median delta.

| File type | Operation | Output | Scope            |   ExifTool med/avg/std ms | ExifModern med/avg/std ms | Modern/Tool ratio | Modern delta ms | Status |
| --------- | --------- | ------ | ---------------- | ------------------------: | ------------------------: | ----------------: | --------------: | ------ |
| `JPG`     | `read`    | `json` | `(11.0 MiB JPG)` |   84.968 / 85.534 / 1.189 | 129.737 / 131.457 / 6.590 |             1.527 |          44.769 | ok/ok  |
| `JPG`     | `read`    | `text` | `(11.0 MiB JPG)` |   85.230 / 85.088 / 1.596 | 127.401 / 127.066 / 2.561 |             1.495 |          42.171 | ok/ok  |
| `MOV`     | `read`    | `text` | `(57.3 MiB MOV)` | 129.204 / 129.527 / 1.511 | 104.431 / 104.596 / 1.526 |             0.808 |         -24.773 | ok/ok  |
| `MOV`     | `read`    | `json` | `(57.3 MiB MOV)` | 136.752 / 136.764 / 1.620 | 105.677 / 105.479 / 1.483 |             0.773 |         -31.075 | ok/ok  |
| `MP4`     | `read`    | `text` | `(6.0 MiB MP4)`  |   76.369 / 76.448 / 0.910 |   84.799 / 84.816 / 1.375 |             1.110 |           8.430 | ok/ok  |
| `MP4`     | `read`    | `json` | `(6.0 MiB MP4)`  |   83.679 / 83.875 / 0.648 |   85.435 / 85.736 / 0.971 |             1.021 |           1.756 | ok/ok  |

## Long-Running Transports

| Operation | Output         | Scope             | ExifTool stdin med/avg/std ms | ExifModern stdin med/avg/std ms | ExifModern persistent server TCP request med/avg/std ms | ExifModern spawned exifc client request med/avg/std ms | Spawned client overhead vs persistent TCP ms | Stdin ratio | Persistent TCP ratio | Spawned client ratio | Output match                   |
| --------- | -------------- | ----------------- | ----------------------------: | ------------------------------: | ------------------------------------------------------: | -----------------------------------------------------: | -------------------------------------------: | ----------: | -------------------: | -------------------- | ------------------------------ |
| `startup` | `help/version` | `process`         |                           n/a |                             n/a |                                   0.853 / 0.855 / 0.112 |                                  4.792 / 4.742 / 0.334 |                                        3.939 |             |                      |                      | n/a                            |
| `listgeo` | `json`         | `GeoNames >=100k` |     312.476 / 313.221 / 2.013 |       390.264 / 390.665 / 2.350 |                                 50.407 / 50.740 / 1.086 |                                62.953 / 66.633 / 6.311 |                                       12.546 |       1.249 |                0.161 | 0.201                | exiftool=True; exifmodern=True |
| `read`    | `text`         | `(6.0 MiB MP4)`   |         4.727 / 4.777 / 0.415 |           1.020 / 1.004 / 0.063 |                                   1.118 / 1.126 / 0.071 |                                  5.291 / 5.290 / 0.286 |                                        4.173 |       0.216 |                0.237 | 1.119                | exiftool=True; exifmodern=True |
| `read`    | `json`         | `(6.0 MiB MP4)`   |         5.107 / 5.070 / 0.328 |           1.267 / 1.256 / 0.080 |                                   1.373 / 1.364 / 0.135 |                                  5.686 / 5.660 / 0.347 |                                        4.313 |       0.248 |                0.269 | 1.113                | exiftool=True; exifmodern=True |
| `read`    | `text`         | `(11.0 MiB JPG)`  |         9.976 / 9.943 / 0.459 |           4.699 / 4.659 / 0.225 |                                   4.584 / 4.585 / 0.170 |                                  9.559 / 9.517 / 0.444 |                                        4.975 |       0.471 |                0.460 | 0.958                | exiftool=True; exifmodern=True |
| `read`    | `json`         | `(11.0 MiB JPG)`  |       10.595 / 10.487 / 0.771 |           5.096 / 5.209 / 0.265 |                                   5.467 / 5.450 / 0.140 |                                10.048 / 10.167 / 0.476 |                                        4.581 |       0.481 |                0.516 | 0.948                | exiftool=True; exifmodern=True |
| `read`    | `text`         | `(57.3 MiB MOV)`  |       15.903 / 15.747 / 0.621 |           3.585 / 3.684 / 0.194 |                                   3.599 / 3.735 / 0.242 |                                  8.464 / 8.537 / 0.317 |                                        4.865 |       0.225 |                0.226 | 0.532                | exiftool=True; exifmodern=True |
| `read`    | `json`         | `(57.3 MiB MOV)`  |       16.508 / 16.541 / 0.664 |           4.356 / 4.323 / 0.262 |                                   4.480 / 4.528 / 0.206 |                                 9.960 / 10.005 / 0.398 |                                        5.480 |       0.264 |                0.271 | 0.603                | exiftool=True; exifmodern=True |
| `read`    | `text`         | `(10.5 MiB JPG)`  |        9.930 / 10.114 / 0.745 |           4.693 / 4.759 / 0.326 |                                   4.889 / 4.946 / 0.207 |                                10.245 / 10.228 / 0.666 |                                        5.356 |       0.473 |                0.492 | 1.032                | exiftool=True; exifmodern=True |
| `read`    | `json`         | `(10.5 MiB JPG)`  |       10.296 / 10.427 / 0.394 |           5.466 / 5.385 / 0.337 |                                   5.176 / 5.181 / 0.128 |                                10.582 / 10.724 / 0.487 |                                        5.406 |       0.531 |                0.503 | 1.028                | exiftool=True; exifmodern=True |

Interpretation:

- Ratio below `1.0` means ExifModern was faster for that scenario.
- Ratio above `1.0` means ExifTool was faster for that scenario.
- `Output match` compares cold stdout to persistent-stdin stdout for each tool after stripping the `{ready}` marker.
- Persistent-stdin measurements keep one server process alive per tool across all eligible scenarios.
- Persistent server TCP measurements keep one `exifmodern server` process and one client TCP connection alive across all eligible scenarios. This is the closest table column to server-side request processing plus JSON/TCP I/O.
- Server+spawned-exifc measurements keep one `exifmodern server` process alive but intentionally start a fresh Rust `exifc` client process per request. This includes client process launch, connect, request, reply, stdout/stderr forwarding, and process exit.
- The spawned `exifc` overhead column is the spawned-client median minus the persistent server TCP median for the same backend and scenario. It includes process launch, TCP connect, JSON framing, request/response I/O, and terminal stdout/stderr forwarding.

<!-- END GENERATED BENCHMARK RESULTS -->

## Performance Guidance

For Python applications, prefer the Python API or a long-lived process so the
application can reuse imports, runtime data caches, and read-path setup.

For non-Python local applications, prefer `exifmodern server` when low latency
matters. A persistent TCP client measures raw server request latency. The
`exifc` binary is a convenient command adapter for shell-style integrations; its
per-call process cost is measured separately by the benchmark.

The remaining optimization targets are cold CLI startup/import cost, public CLI
request-path overhead, and any format-specific read path that still materializes
large file payloads unnecessarily.

## Release Practice

Before publishing a public release:

1. Run the benchmark against the current local `../exiftool` reference checkout.
2. Save JSON to `artifacts/benchmarks/exiftool-vs-exifmodern.json`.
3. Save Markdown to `artifacts/benchmarks/exiftool-vs-exifmodern.md`.
4. Run `uv run python scripts/update-performance-doc.py`.
5. Publish or attach the generated Markdown/JSON artifact for the release.
6. Do not hide regressions; mark them as optimization targets with exact
   scenario names and measured deltas.
