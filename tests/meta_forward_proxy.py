"""Local HTTP CONNECT proxy forwarding encrypted requests to actual Meta.

The test proxy does not fabricate ads, terminate TLS, or record request bodies.
It optionally checks ephemeral Basic proxy credentials generated in the test.
"""

from __future__ import annotations

import base64
import contextlib
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MetaForwardProxy:
    def __init__(self, username: str | None = None, password: str | None = None):
        self.connections: list[str] = []
        self.username = username
        self.password = password
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
                    remote = socket.create_connection((host, int(port)), timeout=30)
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
        self.username = username
        self.password = password
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
                    with socket.create_connection((host, port), timeout=30) as remote:
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
