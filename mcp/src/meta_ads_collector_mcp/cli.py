"""Stdio and persistent-worker commands; core installs need no MCP imports."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Meta Ad Library MCP and durable monitoring worker")
    parser.add_argument("mode", nargs="?", choices=("serve", "worker", "discover"), default="serve")
    parser.add_argument(
        "--data-dir", default=os.environ.get("METAADS_MCP_DATA_DIR", str(Path.home() / ".meta-ads-collector-mcp"))
    )
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=2)
    parser.add_argument(
        "--proxy-env", help="Private environment variable containing proxy URL(s); never put credentials in arguments"
    )
    parser.add_argument("--once", action="store_true", help="Worker only: run one scheduling pass and finish its jobs")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("The MCP extension requires Python 3.10+; the core collector still supports Python 3.9")
    try:
        from mcp.server import MCPServer  # noqa: F401
    except ImportError:
        parser.error('Install the optional extension: pip install "meta-ads-collector[mcp]"')
    from .config import configure_logs
    from .schemas import ProxyProfile
    from .service import Service

    configure_logs()
    service = Service(args.data_dir, args.concurrency)
    try:
        if args.proxy_env:
            service.proxy("configure", ProxyProfile(name="startup", environment=args.proxy_env))
            service.proxy("default", name="startup")
        if args.mode == "discover":
            print(json.dumps(service.capabilities(), indent=2))
        elif args.mode == "worker":

            def stop(signum, frame):
                service.stop.set()

            signal.signal(signal.SIGINT, stop)
            signal.signal(signal.SIGTERM, stop)
            service.persistent = True
            if args.once:
                service.store.worker_heartbeat(service.owner)
                service.tick()
                for future in list(service.futures.values()):
                    future.result()
            else:
                service.start(persistent=True)
                service.stop.wait()
        else:
            from .server import create_server

            create_server(service).run(transport="stdio")
    except Exception as exc:
        from .engine import error_info

        print(json.dumps(error_info(exc)), file=sys.stderr)
        return 1
    finally:
        service.close()
    return 0
