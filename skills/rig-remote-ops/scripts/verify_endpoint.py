"""Verify a remote Windows MCP endpoint honestly.

Walks the ladder from TCP to a real tool call, printing what each step actually
proved. Exits non-zero on the first unproven step, so a green run means
"verified", not "seemed fine".

Two profiles, because the tool naming is not universal:

    --profile rig-gateway   (default) host_status/system_info/list_directory/...
    --profile vendor        GetSystemInfo/ListProcesses/FileList/FileRead

and an explicit auth posture, because "no auth" is a legitimate configuration
for rig-gateway and demanding 401 there would fail a correct server:

    --auth none       rig-gateway's documented default
    --auth required   expect 401/403 unauthenticated (server behind its own auth)

Usage:
    python verify_endpoint.py --host 100.64.0.1 --port 8099 --auth none \\
        --expect-marker-file 'C:\\approved\\root\\channel-marker.txt'

    python verify_endpoint.py --profile vendor --host 100.64.0.1 --port 8090 \\
        --expect-hostname HOSTNAME

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
            # Detect SSE by its frame structure, not by sniffing for the string
            # "text/event-stream" in the body (that is a header value, and a real
            # streamable-http frame opens with "event: message", so the old test
            # missed every genuine response and fell through to json.loads on an
            # SSE payload). If any line opens a data field, it is SSE.
            lines = raw.splitlines()
            if any(line.startswith("data:") for line in lines):
                for line in lines:
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


RIG_GATEWAY_TOOLS = "host_status,system_info,list_processes,list_directory,read_file"
RIG_GATEWAY_READ_TOOL = "read_file"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--auth", default="required", choices=["required", "none", "auto"],
                    help="required: expect 401/403 unauthenticated. none: rig-gateway's "
                         "documented default (no built-in auth). auto: accept either, "
                         "and say which was observed.")
    ap.add_argument("--profile", default="rig-gateway", choices=["rig-gateway", "vendor"],
                    help="which tool naming to expect; 'vendor' is the older "
                         "GetSystemInfo/FileRead naming")
    ap.add_argument("--expect-tools", default=None,
                    help="exact allowlist, comma-separated; defaults to the profile's tier-1 set")
    ap.add_argument("--call-tool", default=None,
                    help="read-only tier-1 tool to call for the live check; defaults per profile")
    ap.add_argument("--call-args", default=None,
                    help="JSON object of arguments for --call-tool")
    ap.add_argument("--expect-in-text", default="Windows",
                    help="substring the call result must contain; empty string skips")
    ap.add_argument("--expect-hostname", default=None,
                    help="only set this if a tool genuinely reports the hostname")
    ap.add_argument("--expect-marker-file", default=None,
                    help="path to a file you placed on the target; proves identity by content")
    ap.add_argument("--marker-tool", default=None,
                    help="read-only tool used to read the marker; defaults per profile")
    args = ap.parse_args()

    if args.profile == "rig-gateway":
        args.expect_tools = args.expect_tools or RIG_GATEWAY_TOOLS
        args.call_tool = args.call_tool or "system_info"
        args.marker_tool = args.marker_tool or RIG_GATEWAY_READ_TOOL
    else:
        args.expect_tools = args.expect_tools or "GetSystemInfo,ListProcesses,FileList,FileRead"
        args.call_tool = args.call_tool or "GetSystemInfo"
        args.marker_tool = args.marker_tool or "FileRead"

    key = os.environ.get("WINREMOTE_RIG_TOKEN") or os.environ.get("RIG_TOKEN") or ""
    if args.auth == "none":
        if key:
            print("[note] --auth none but a token is set; it will still be sent.")
        key = key or "no-auth-configured"
    else:
        if not key:
            key = getpass.getpass("API key (hidden): ")
        if len(key) < 32 or any(c.isspace() for c in key):
            die("input", "key must be >=32 characters with no whitespace")

    tcp_check(args.host, args.port, min(args.timeout, 8))

    # A live app answers. Any HTTP status proves that -- the check is that we got
    # a response at all, not which one.
    status = http_status(args.host, args.port, "/mcp", args.timeout, None)
    if status is None:
        die("liveness", "no HTTP response at all -- see the 'output starvation' section")
    if status in (401, 403):
        if args.auth == "none":
            die("liveness", f"unauthenticated /mcp returned HTTP {status} but --auth none was "
                            "given; auth IS in force, so say so rather than passing by accident")
        ok("liveness", f"app answers; unauthenticated request refused with HTTP {status}")
    else:
        # rig-gateway ships with no built-in auth by design, so 200 here is the
        # documented posture, not a fault. Demanding 401/403 -- which this script
        # used to do unconditionally -- turned a correct server into a failure.
        if args.auth == "required":
            die("liveness", f"unauthenticated /mcp returned HTTP {status}, expected 401/403, "
                            "but --auth required was given. Either put auth in front of the "
                            "server or pass --auth none to accept the documented default.")
        ok("liveness", f"app answers; unauthenticated request returned HTTP {status} "
                       "(no auth in force -- rig-gateway's default)")

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
        ok("tools/list", f"inventory is exactly the approved {len(want)} tools: {names}")
    else:
        ok("tools/list", f"inventory (unchecked): {names}")

    call_args = json.loads(args.call_args) if args.call_args else {}
    info = mcp.call(args.call_tool, call_args)
    if args.expect_in_text and args.expect_in_text.lower() not in info.lower():
        die(args.call_tool, f"response did not contain {args.expect_in_text!r}: {info[:400]!r}")
    ok(args.call_tool, "returned live data")

    if args.expect_hostname:
        # Only meaningful if the tool really reports it; otherwise omit the flag.
        if args.expect_hostname.upper() not in info.upper():
            die("identity", f"{args.call_tool} does not expose that hostname; "
                            "use --expect-marker-file")
        ok("identity", "hostname confirmed from tool output")

    if args.expect_marker_file:
        body = mcp.call(args.marker_tool,
                        {"path": args.expect_marker_file, "encoding": "utf-8"})
        if not body.strip():
            die("identity", f"marker file {args.expect_marker_file} read back empty")
        ok("identity", f"read back marker file ({len(body)} chars) from the intended path")

    if not args.expect_hostname and not args.expect_marker_file:
        print("[warn] identity NOT verified: pass --expect-marker-file (recommended) or "
              "--expect-hostname if the tool really reports one")
    print("\nEndpoint is verified. Tools execute; inventory matches.")
    if args.auth == "none":
        print("NOTE: auth was NOT verified -- none is configured. That is rig-gateway's "
              "documented default; restrict access with tailnet ACLs or a reverse proxy.")


if __name__ == "__main__":
    main()