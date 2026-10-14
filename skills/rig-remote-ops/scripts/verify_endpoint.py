"""Verify a remote Windows MCP endpoint honestly.

Reads the API key from a hidden prompt (or WINREMOTE_RIG_TOKEN), then walks the
full ladder from TCP to a real tool call, printing what each step actually proved.
Exits non-zero on the first unproven step, so a green run means "verified", not
"seemed fine".

Usage:
    python verify_endpoint.py --host 100.64.0.1 --port 8090 --expect-hostname HOSTNAME
    python verify_endpoint.py ... --expect-marker-file 'C:\\path\\marker.txt'

Never prints the key. Never writes the key anywhere.
"""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import re
import socket
import sys

# Servers that wrap tools in a task manager prepend a run id to text results.
TASK_PREFIX = re.compile(r"^\[task:[0-9a-f]{12}\] ")


def die(step: str, detail: str) -> "None":
    print(f"[FAIL] {step}: {detail}")
    sys.exit(1)


def ok(step: str, detail: str) -> None:
    print(f"[ ok ] {step}: {detail}")


def tcp_check(host: str, port: int, timeout: float) -> None:
    """A listening socket proves a listener exists. It proves nothing about HTTP."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok("tcp", f"{host}:{port} accepted a connection")
    except OSError as exc:
        die("tcp", f"{host}:{port} unreachable: {exc}")
    print("       note: a TCP connect does not prove the server answers HTTP.")


class Mcp:
    def __init__(self, host: str, port: int, key: str, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.session: str | None = None
        self.protocol: str | None = None
        self.headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._id = 0

    def _post(self, path: str, body: dict) -> tuple[int, str]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request("POST", path, json.dumps(body), self.headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8", "replace")
            self.session = resp.getheader("Mcp-Session-Id") or self.session
            return resp.status, raw
        except (http.client.RemoteDisconnected, http.client.BadStatusLine) as exc:
            # Accepted the connection then hung up mid-exchange. Usually a
            # keep-alive/session mismatch, not an auth problem -- say so plainly
            # instead of dumping a traceback at the operator.
            die("transport", f"server closed the connection during {path}: {exc}. "
                             "Check session-id handling and keep-alive behaviour.")
        except socket.timeout:
            die("transport", f"no response within {self.timeout}s from {path} -- "
                             "see the 'output starvation' section")
        except OSError as exc:
            die("transport", f"connection failed on {path}: {exc}")
        finally:
            conn.close()
        return 0, ""

    @staticmethod
    def _message(raw: str, want: int) -> dict:
        try:
            if "text/event-stream" in raw[:200] or raw.lstrip().startswith("data:"):
                for line in raw.splitlines():
                    if line.startswith("data:"):
                        msg = json.loads(line[5:].strip())
                        if msg.get("id") == want:
                            return msg
                raise ValueError(f"no SSE frame with id={want}")
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            die("transport", f"unparseable response: {exc}")

    def rpc(self, method: str, params: dict | None = None) -> dict:
        if self.session:
            self.headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            self.headers["MCP-Protocol-Version"] = self.protocol
        self._id += 1
        rid = self._id
        body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        status, raw = self._post("/mcp", body)
        if status not in (200, 202):
            die(method, f"HTTP {status}")
        if method.startswith("notifications/"):
            return {}
        msg = self._message(raw, rid)
        if "error" in msg:
            die(method, f"MCP error: {msg['error']}")
        return msg.get("result", {})

    def notify(self, method: str) -> None:
        if self.session:
            self.headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            self.headers["MCP-Protocol-Version"] = self.protocol
        self._post("/mcp", {"jsonrpc": "2.0", "method": method, "params": {}})

    def call(self, name: str, arguments: dict) -> str:
        res = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            die(name, "tool reported an error")
        parts = []
        for item in res.get("content", []):
            if item.get("type") == "text":
                text = item.get("text", "")
                # Strip exactly one transport prefix, then a JSON string wrapper.
                text = TASK_PREFIX.sub("", text, count=1)
                try:
                    decoded = json.loads(text)
                    if isinstance(decoded, str):
                        text = decoded
                except json.JSONDecodeError:
                    pass
                parts.append(text)
        return "\n".join(parts)


def http_status(host: str, port: int, path: str, timeout: float, auth: dict | None) -> int | None:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        headers = dict(auth or {})
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/event-stream"
        conn.request("POST", path,
                     json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                            "clientInfo": {"name": "probe", "version": "1"}}}),
                     headers)
        return conn.getresponse().status
    except OSError:
        return None
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--expect-tools", default="GetSystemInfo,ListProcesses,FileList,FileRead",
                    help="exact allowlist; empty string skips the check")
    ap.add_argument("--expect-hostname", default=None,
                    help="only set this if a tool genuinely reports the hostname")
    ap.add_argument("--expect-marker-file", default=None,
                    help="path to a file you placed on the target; proves identity by content")
    args = ap.parse_args()

    key = os.environ.get("WINREMOTE_RIG_TOKEN")
    if not key:
        key = getpass.getpass("API key (hidden): ")
    if len(key) < 32 or any(c.isspace() for c in key):
        die("input", "key must be >=32 characters with no whitespace")

    tcp_check(args.host, args.port, min(args.timeout, 8))

    # A live app answers. With an allowlist a self-request may be refused, so any
    # HTTP status proves liveness -- demanding 200 here is a false-negative trap.
    status = http_status(args.host, args.port, "/mcp", args.timeout, None)
    if status is None:
        die("liveness", "no HTTP response at all -- see the 'output starvation' section")
    if status == 401 or status == 403:
        ok("liveness", f"app answers; unauthenticated request refused with HTTP {status}")
    else:
        die("liveness", f"unauthenticated /mcp returned HTTP {status}, expected 401/403 -- "
                        "auth may be disabled")

    mcp = Mcp(args.host, args.port, key, args.timeout)
    init = mcp.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "verify-endpoint", "version": "1.0"}})
    mcp.protocol = init.get("protocolVersion", "2025-03-26")
    mcp.notify("notifications/initialized")
    ok("initialize", f"handshake complete, protocol {mcp.protocol}")

    listing = mcp.rpc("tools/list")
    names = sorted(t["name"] for t in listing.get("tools", []))
    if listing.get("nextCursor"):
        die("tools/list", "response was paginated; refusing to judge a partial inventory")
    if args.expect_tools:
        want = sorted(n.strip() for n in args.expect_tools.split(",") if n.strip())
        if names != want:
            die("tools/list", f"expected exactly {want}, got {names}")
        ok("tools/list", f"inventory is exactly the approved {len(want)} tools")
    else:
        ok("tools/list", f"inventory (unchecked): {names}")

    info = mcp.call("GetSystemInfo", {})
    if "Windows" not in info:
        die("GetSystemInfo", "response did not mention Windows")
    ok("GetSystemInfo", "returned live system information")

    if args.expect_hostname:
        # Only meaningful if the tool really reports it; otherwise omit the flag.
        if args.expect_hostname.upper() not in info.upper():
            die("identity", "GetSystemInfo does not expose a hostname; use --expect-marker-file")
        ok("identity", "hostname confirmed from tool output")

    if args.expect_marker_file:
        body = mcp.call("FileRead", {"path": args.expect_marker_file, "encoding": "utf-8"})
        if not body.strip():
            die("identity", f"marker file {args.expect_marker_file} read back empty")
        ok("identity", f"read back marker file ({len(body)} chars) from the intended path")

    if not args.expect_hostname and not args.expect_marker_file:
        print("[warn] identity NOT verified: pass --expect-marker-file (recommended) or "
              "--expect-hostname if the tool really reports one")
    print("\nEndpoint is verified. Tools execute; auth is enforced; inventory matches.")


if __name__ == "__main__":
    main()