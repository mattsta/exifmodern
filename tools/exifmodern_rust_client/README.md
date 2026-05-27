# exifc

`exifc` is the optional Rust command adapter for the long-running
`exifmodern server` backend. It does not embed or spawn ExifModern. It connects
to an already-running local server, sends one CLI-compatible request, prints the
returned stdout/stderr streams, and exits with the backend exit code.

Build:

```sh
cargo build --release --manifest-path tools/exifmodern_rust_client/Cargo.toml
```

Install:

```sh
install -m 0755 tools/exifmodern_rust_client/target/release/exifc ~/.local/bin/exifc
```

Run:

```sh
exifmodern server --host 127.0.0.1 --port 8765
exifc --host 127.0.0.1 --port 8765 -- read --format json image.jpg
```

Unix-domain sockets are supported on Unix platforms:

```sh
exifmodern server --unix-socket /tmp/exifmodern.sock
exifc --unix-socket /tmp/exifmodern.sock -- read image.jpg
```
