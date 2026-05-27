use serde::{Deserialize, Serialize};
use std::env;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process;
use std::time::Duration;

#[cfg(unix)]
use std::os::unix::net::UnixStream;

const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_TIMEOUT_MS: u64 = 30_000;
const PROTOCOL: &str = "exifmodern-jsonl-v1";

#[derive(Debug)]
struct ClientConfig {
    host: String,
    port: Option<u16>,
    unix_socket: Option<String>,
    timeout: Duration,
    argv: Vec<String>,
}

#[derive(Serialize)]
struct Request<'a> {
    protocol: &'a str,
    argv: &'a [String],
}

#[derive(Deserialize)]
struct Response {
    protocol: Option<String>,
    ok: Option<bool>,
    exit_code: i32,
    stdout: String,
    stderr: String,
}

fn main() {
    match run() {
        Ok(exit_code) => process::exit(exit_code),
        Err(message) => {
            eprintln!("{message}");
            process::exit(2);
        }
    }
}

fn run() -> Result<i32, String> {
    let config = parse_args(env::args().skip(1))?;
    if let Some(socket_path) = &config.unix_socket {
        return run_unix_client(socket_path, &config);
    }
    let port = config
        .port
        .ok_or_else(|| "--port or --unix-socket is required".to_string())?;
    let addr: SocketAddr = format!("{}:{}", config.host, port)
        .parse()
        .map_err(|error| format!("invalid server address: {error}"))?;
    let stream = TcpStream::connect_timeout(&addr, config.timeout)
        .map_err(|error| format!("failed to connect to {addr}: {error}"))?;
    stream
        .set_read_timeout(Some(config.timeout))
        .map_err(|error| format!("failed to set read timeout: {error}"))?;
    stream
        .set_write_timeout(Some(config.timeout))
        .map_err(|error| format!("failed to set write timeout: {error}"))?;

    exchange_with_server(stream, &config)
}

#[cfg(unix)]
fn run_unix_client(socket_path: &str, config: &ClientConfig) -> Result<i32, String> {
    let stream = UnixStream::connect(socket_path)
        .map_err(|error| format!("failed to connect to {socket_path}: {error}"))?;
    stream
        .set_read_timeout(Some(config.timeout))
        .map_err(|error| format!("failed to set read timeout: {error}"))?;
    stream
        .set_write_timeout(Some(config.timeout))
        .map_err(|error| format!("failed to set write timeout: {error}"))?;
    exchange_with_server(stream, config)
}

#[cfg(not(unix))]
fn run_unix_client(_socket_path: &str, _config: &ClientConfig) -> Result<i32, String> {
    Err("--unix-socket is only supported on Unix platforms".to_string())
}

trait ReadWrite: Read + Write {}

impl<T> ReadWrite for T where T: Read + Write {}

fn exchange_with_server<S>(mut stream: S, config: &ClientConfig) -> Result<i32, String>
where
    S: ReadWrite,
{
    let request = Request {
        protocol: PROTOCOL,
        argv: &config.argv,
    };
    let mut request_line = serde_json::to_vec(&request)
        .map_err(|error| format!("failed to encode request: {error}"))?;
    request_line.push(b'\n');
    stream
        .write_all(&request_line)
        .map_err(|error| format!("failed to write request: {error}"))?;

    let mut response_line = String::new();
    let mut reader = BufReader::new(stream);
    reader
        .read_line(&mut response_line)
        .map_err(|error| format!("failed to read response: {error}"))?;
    if response_line.is_empty() {
        return Err("server closed connection without a response".to_string());
    }
    let response: Response = serde_json::from_str(&response_line)
        .map_err(|error| format!("failed to decode response JSON: {error}"))?;
    if response.protocol.as_deref() != Some(PROTOCOL) {
        return Err("server response used an unsupported protocol".to_string());
    }

    print!("{}", response.stdout);
    eprint!("{}", response.stderr);
    let _server_ok = response.ok.unwrap_or(response.exit_code == 0);
    Ok(response.exit_code)
}

fn parse_args<I>(args: I) -> Result<ClientConfig, String>
where
    I: IntoIterator<Item = String>,
{
    let mut host = DEFAULT_HOST.to_string();
    let mut port: Option<u16> = None;
    let mut unix_socket: Option<String> = None;
    let mut timeout_ms = DEFAULT_TIMEOUT_MS;
    let mut argv = Vec::new();
    let mut iter = args.into_iter().peekable();

    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--host" => {
                host = iter
                    .next()
                    .ok_or_else(|| "--host requires a value".to_string())?;
            }
            "--port" => {
                let raw_port = iter
                    .next()
                    .ok_or_else(|| "--port requires a value".to_string())?;
                port = Some(
                    raw_port
                        .parse()
                        .map_err(|error| format!("invalid --port value: {error}"))?,
                );
            }
            "--unix-socket" => {
                unix_socket = Some(
                    iter.next()
                        .ok_or_else(|| "--unix-socket requires a value".to_string())?,
                );
            }
            "--timeout-ms" => {
                let raw_timeout = iter
                    .next()
                    .ok_or_else(|| "--timeout-ms requires a value".to_string())?;
                timeout_ms = raw_timeout
                    .parse()
                    .map_err(|error| format!("invalid --timeout-ms value: {error}"))?;
            }
            "-h" | "--help" => {
                return Err(help_text());
            }
            "--" => {
                argv.extend(iter);
                break;
            }
            _ => {
                argv.push(arg);
                argv.extend(iter);
                break;
            }
        }
    }

    if port.is_some() && unix_socket.is_some() {
        return Err("--port and --unix-socket are mutually exclusive".to_string());
    }
    if port.is_none() && unix_socket.is_none() {
        return Err("--port or --unix-socket is required".to_string());
    }
    if timeout_ms == 0 {
        return Err("--timeout-ms must be positive".to_string());
    }
    Ok(ClientConfig {
        host,
        port,
        unix_socket,
        timeout: Duration::from_millis(timeout_ms),
        argv,
    })
}

fn help_text() -> String {
    "usage: exifc (--port PORT [--host HOST] | --unix-socket PATH) [--timeout-ms MS] -- [EXIFMODERN_ARGS...]".to_string()
}
