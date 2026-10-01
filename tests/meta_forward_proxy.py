"""Local HTTP CONNECT proxy forwarding encrypted requests to actual Meta.

The test proxy does not fabricate ads, terminate TLS, or record request bodies.
It optionally checks ephemeral Basic proxy credentials generated in the test.
"""

from __future__ import annotations

import base64
import contextlib
import os
import select
import socket
import socketserver
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from meta_ads_collector.proxy_pool import parse_proxy


def _connect_remote(host, port, upstream, server_name=None):
    """Open an opaque Meta tunnel, optionally through a private CI proxy."""
    if not upstream:
        return socket.create_connection((host, port), timeout=30)
    proxy = urlsplit(upstream)
    username = unquote(proxy.username) if proxy.username is not None else None
    password = unquote(proxy.password) if proxy.password is not None else None
    if proxy.scheme in {"http", "https"}:
        remote = socket.create_connection((proxy.hostname, proxy.port), timeout=30)
        try:
            if proxy.scheme == "https":
                import certifi
                context = ssl.create_default_context(cafile=certifi.where())
                remote = context.wrap_socket(remote, server_hostname=proxy.hostname)
            target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            # Residential gateways can require the original hostname in Host
            # even when the SOCKS client supplied a locally resolved Meta IP.
            # Preserve that IP in the CONNECT request target.
            authority = f"{server_name}:{port}" if server_name else target
            lines = [f"CONNECT {target} HTTP/1.1", f"Host: {authority}"]
            if username is not None:
                credential = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
                lines.append(f"Proxy-Authorization: Basic {credential}")
            remote.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            header = b""
            while not header.endswith(b"\r\n\r\n") and len(header) < 16384:
                byte = remote.recv(1)
                if not byte:
                    raise OSError("Upstream proxy closed the CONNECT handshake")
                header += byte
            if not header.endswith(b"\r\n\r\n"):
                raise OSError("Upstream proxy CONNECT headers exceeded the limit")
            status = header.split(b"\r\n", 1)[0].split()
            if len(status) < 2 or status[1] != b"200":
                raise OSError("Upstream proxy refused the CONNECT tunnel")
            return remote
        except Exception:
            remote.close()
            raise
    import socks
    kind = socks.SOCKS4 if proxy.scheme in {"socks4", "socks4a"} else socks.SOCKS5
    remote = socks.socksocket()
    try:
        remote.set_proxy(kind, proxy.hostname, proxy.port,
                         rdns=proxy.scheme in {"socks4a", "socks5h"},
                         username=username, password=password)
        remote.settimeout(30)
        remote.connect((host, port))
        return remote
    except Exception:
        remote.close()
        raise


class MetaForwardProxy:
    def __init__(self, username: str | None = None, password: str | None = None):
        self.connections: list[str] = []
        self.username = username
        self.password = password
        configured = os.environ.get("METAADS_CI_PROXY")
        self.upstream = parse_proxy(configured) if configured else None
        self.stop = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_CONNECT(self):
                if owner.username is not None:
                    expected = "Basic " + base64.b64encode(
                        f"{owner.username}:{owner.password}".encode()
                    ).decode()
                    if self.headers.get("Proxy-Authorization") != expected:
                        self.send_response(407)
                        self.send_header("Proxy-Authenticate", 'Basic realm="Meta test"')
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                host, separator, port = self.path.rpartition(":")
                is_meta = host in {"www.facebook.com", "facebook.com"} or host.endswith(".fbcdn.net")
                if not separator or not is_meta or port != "443":
                    self.send_error(403)
                    return
                try:
                    remote = _connect_remote(host, int(port), owner.upstream)
                except OSError:
                    self.send_error(502)
                    return
                with remote:
                    owner.connections.append(host)
                    self.send_response(200, "Connection established")
                    self.end_headers()
                    self.wfile.flush()
                    sockets = [self.connection, remote]
                    while not owner.stop.is_set():
                        ready, _, _ = select.select(sockets, [], [], 1)
                        for incoming in ready:
                            try:
                                data = incoming.recv(65536)
                                if not data:
                                    return
                                outgoing = remote if incoming is self.connection else self.connection
                                outgoing.sendall(data)
                            except OSError:
                                return

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def host_port(self) -> str:
        return f"127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.server.shutdown()
        with contextlib.suppress(OSError):
            self.server.server_close()
        self.thread.join(timeout=5)


class MetaSocksProxy(MetaForwardProxy):
    """SOCKS5 server relaying actual HTTPS traffic, with RFC 1929 authentication."""

    def __init__(self, username: str, password: str):
        self.connections = []
        self.meta_addresses = {
            row[4][0] for row in socket.getaddrinfo("www.facebook.com", 443, type=socket.SOCK_STREAM)
        }
        self.username = username
        self.password = password
        configured = os.environ.get("METAADS_CI_PROXY")
        self.upstream = parse_proxy(configured) if configured else None
        self.stop = threading.Event()
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(30)
                try:
                    greeting = self.rfile.read(2)
                    if len(greeting) != 2 or greeting[0] != 5:
                        return
                    methods = self.rfile.read(greeting[1])
                    if 2 not in methods:
                        self.wfile.write(b"\x05\xff")
                        return
                    self.wfile.write(b"\x05\x02")
                    auth = self.rfile.read(2)
                    if len(auth) != 2 or auth[0] != 1:
                        return
                    user = self.rfile.read(auth[1]).decode()
                    length = self.rfile.read(1)
                    if not length:
                        return
                    password = self.rfile.read(length[0]).decode()
                    if user != owner.username or password != owner.password:
                        self.wfile.write(b"\x01\x01")
                        return
                    self.wfile.write(b"\x01\x00")
                    request = self.rfile.read(4)
                    if len(request) != 4 or request[:3] != b"\x05\x01\x00":
                        return
                    if request[3] == 1:
                        host = socket.inet_ntoa(self.rfile.read(4))
                    elif request[3] == 3:
                        host = self.rfile.read(self.rfile.read(1)[0]).decode()
                    elif request[3] == 4:
                        host = socket.inet_ntop(socket.AF_INET6, self.rfile.read(16))
                    else:
                        return
                    port = int.from_bytes(self.rfile.read(2), "big")
                    if port != 443:
                        return
                    server_name = "www.facebook.com" if host in owner.meta_addresses else None
                    with _connect_remote(host, port, owner.upstream, server_name) as remote:
                        owner.connections.append(host)
                        self.wfile.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                        while not owner.stop.is_set():
                            ready, _, _ = select.select([self.connection, remote], [], [], 1)
                            for incoming in ready:
                                data = incoming.recv(65536)
                                if not data:
                                    return
                                outgoing = remote if incoming is self.connection else self.connection
                                outgoing.sendall(data)
                except (OSError, ValueError, IndexError):
                    return

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def host_port(self) -> str:
        return f"127.0.0.1:{self.server.server_address[1]}"
