"""Negative tests: the verifier must reject things that merely look healthy."""
from __future__ import annotations

import json
import contextlib
import importlib.util
import io
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERIFIER = Path(__file__).resolve().parents[1] / "skills" / "rig-remote-ops" / "scripts" / "verify_endpoint.py"
KEY = "k" * 40

STARVED = r'''
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(64)
held = []
while True:                 # accept, then never reply: alive on the socket, silent on HTTP
    c, _ = s.accept(); held.append(c)
'''

# Accept, then close WITHOUT sending a byte. Same "no response" symptom as
# STARVED, different cause: an active refusal rather than a stall. This is what
# the AweSun API does when it rejects a credential, and reading it as a network
# fault cost real time. The verifier must name the right one.
CLOSED = r'''
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(64)
while True:
    c, _ = s.accept()
    c.close()               # no bytes at all
'''

MCP = r'''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
KEY = sys.argv[2]
TOOLS = [{"name": n, "description": n, "inputSchema": {"type": "object"}}
         for n in ["GetSystemInfo", "ListProcesses", "FileList", "FileRead"]]
MARKER = "channel-marker-8f21a4"
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, obj, code=200, extra=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer " + KEY:
            self._send({"error": "Unauthorized"}, 401); return
        n = int(self.headers.get("Content-Length") or 0)
        msg = json.loads(self.rfile.read(n) or b"{}")
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            self._send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2025-03-26",
                        "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}},
                       extra={"Mcp-Session-Id": "sess1"})
        elif m == "tools/list":
            self._send({"jsonrpc": "2.0", "id": i, "result": {"tools": TOOLS}})
        elif m == "tools/call":
            name = msg["params"]["name"]
            path = msg["params"].get("arguments", {}).get("path", "")
            text = ("[task:0123456789ab] **System:** Windows 11 (AMD64)" if name == "GetSystemInfo"
                    else MARKER)
            self._send({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": text}]}})
        else:
            self._send({"jsonrpc": "2.0", "id": i, "result": {}})
    def do_GET(self):
        self._send({"status": "ok"})
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''

LEAKY = MCP.replace(
    '"tools": TOOLS}', '"tools": TOOLS + [{"name": "Shell", "description": "pwsh", "inputSchema": {"type":"object"}}]}')

# The same vendor naming, but with the auth gate removed -- what a server with
# no auth in front of it actually looks like.
NOAUTH_MCP = MCP.replace(
    '        auth = self.headers.get("Authorization", "")\n'
    '        if auth != "Bearer " + KEY:\n'
    '            self._send({"error": "Unauthorized"}, 401); return\n', '')

EXTRA_TOOLS = ["GetSystemInfo", "ListProcesses", "FileList", "FileRead"]

# A stand-in for rig-gateway: tier-1 only, lowercase names, and -- the point --
# NO authorization header required, which is its documented default.
RIG_MCP = r'''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
TIER1 = ["host_status", "system_info", "list_processes", "list_directory", "read_file"]
TOOLS = [{"name": n, "description": n, "inputSchema": {"type": "object"}} for n in TIER1]
MARKER = "channel-marker-8f21a4"
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.headers.get("Authorization"):
            self._send({"error": "unexpected credentials"}, 403); return
        n = int(self.headers.get("Content-Length") or 0)
        msg = json.loads(self.rfile.read(n) or b"{}")
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            self._send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2025-03-26",
                        "capabilities": {}, "serverInfo": {"name": "rig-fake", "version": "1"}}})
        elif m == "tools/list":
            self._send({"jsonrpc": "2.0", "id": i, "result": {"tools": TOOLS}})
        elif m == "tools/call":
            name = msg["params"]["name"]
            if name == "system_info":
                payload = {"system": "Windows 11 (AMD64)", "hostname": "RIG-FAKE", "sandbox_root": "(unset)"}
            elif name == "read_file":
                payload = MARKER
            else:
                payload = {"ok": True}
            self._send({"jsonrpc": "2.0", "id": i,
                        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}})
        else:
            self._send({"jsonrpc": "2.0", "id": i, "result": {}})
    def do_GET(self):
        self._send({"status": "ok"})
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''

RIG_LEAKY = RIG_MCP.replace('TIER1 = ["host_status", "system_info", "list_processes", "list_directory", "read_file"]',
                            'TIER1 = ["host_status", "system_info", "list_processes", "list_directory", "read_file", "write_file"]')


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn(code: str, port: int, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", code, str(port), *args],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_verifier(port: int, *extra: str) -> tuple[int, str]:
    env = dict(os.environ, WINREMOTE_RIG_TOKEN=KEY)
    proc = subprocess.run([sys.executable, "-I", str(VERIFIER), "--host", "127.0.0.1",
                           "--port", str(port), "--timeout", "6", *extra],
                          capture_output=True, text=True, env=env, timeout=120)
    return proc.returncode, proc.stdout


class CodexEntryTests(unittest.TestCase):
    def test_effective_entry_is_checked_without_contacting_the_configured_url(self):
        spec = importlib.util.spec_from_file_location("verify_endpoint", VERIFIER)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        cases = [
            ("http://127.0.0.1:8123/mcp", True, True),
            ("http://127.0.0.1:8124/mcp", True, False),
            ("http://127.0.0.1:8123/mcp", False, False),
            ("https://127.0.0.1:8123/mcp", True, False),
            ("http://other-host:8123/mcp", True, False),
            ("http://127.0.0.1:8123/mcp?token=private-value", True, False),
        ]
        for url, enabled, expected in cases:
            with self.subTest(url=url, enabled=enabled):
                entry = {"enabled": enabled, "transport": {"type": "streamable_http", "url": url}}
                reply = subprocess.CompletedProcess([], 0, stdout=json.dumps(entry).encode())
                output = io.StringIO()
                with patch.object(verifier.subprocess, "run", return_value=reply) as get_entry:
                    with contextlib.redirect_stdout(output):
                        if expected:
                            verifier.check_codex_entry("rig-test", "127.0.0.1", 8123)
                        else:
                            with self.assertRaises(SystemExit):
                                verifier.check_codex_entry("rig-test", "127.0.0.1", 8123)
                self.assertEqual(get_entry.call_args.args[0], ["codex", "mcp", "get", "rig-test", "--json"])
                self.assertNotIn("private-value", output.getvalue())


class VerifierTests(unittest.TestCase):
    """The vendor profile, kept because that naming is still in the field."""

    def setUp(self):
        self._servers: list[subprocess.Popen] = []

    def tearDown(self):
        for proc in self._servers:
            proc.kill()
            proc.wait()
        time.sleep(0.4)

    def _serve(self, code: str, *args: str) -> int:
        port = free_port()
        proc = spawn(code, port, *args)
        self._servers.append(proc)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                    return port
            except OSError:
                time.sleep(0.2)
        self.fail("test server never started")

    def test_unreachable_host_fails(self):
        rc, _ = run_verifier(free_port(), "--profile", "vendor")
        self.assertNotEqual(rc, 0)

    def test_retry_recovers_when_listener_starts_late(self):
        port = free_port()
        self._servers.append(spawn("import time; time.sleep(1.5)\n" + RIG_MCP, port))
        rc, out = run_verifier(port, "--auth", "none", "--timeout", "0.5", "--connect-attempts", "3")
        self.assertEqual(rc, 0, out)
        self.assertIn("[retry] tcp", out)
        self.assertIn("inventory is exactly", out)

    def test_rejected_initialized_notification_stops_verification(self):
        server = RIG_MCP.replace('elif m == "tools/list":',
                                 'elif m == "notifications/initialized": self._send({}, 503)\n'
                                 '        elif m == "tools/list":')
        port = self._serve(server)
        rc, out = run_verifier(port, "--auth", "none", "--connect-attempts", "3")
        self.assertNotEqual(rc, 0)
        self.assertIn("notifications/initialized: HTTP 503", out)
        self.assertNotIn("[retry]", out)

    def test_starved_listener_is_rejected(self):
        """The regression guard: a socket that accepts but never answers must FAIL."""
        port = self._serve(STARVED)
        rc, out = run_verifier(port, "--profile", "vendor")
        self.assertNotEqual(rc, 0, "a listening-but-silent server must not pass")
        self.assertIn("liveness", out)

    def test_silent_close_is_rejected_and_named_as_a_drop(self):
        """Accepts then closes with no bytes: an active refusal, not a stall.

        Both this and STARVED produce "no HTTP response", so a verifier that
        collapses them sends the operator to debug the wrong layer. The message
        must distinguish them.
        """
        port = self._serve(CLOSED)
        rc, out = run_verifier(port, "--profile", "vendor")
        self.assertNotEqual(rc, 0, "a server that drops the connection must not pass")
        self.assertIn("closed it without sending", out)
        self.assertNotIn("output-starvation signature", out)

    def test_healthy_server_passes_all_checks(self):
        port = self._serve(MCP, KEY)
        rc, out = run_verifier(port, "--profile", "vendor")
        self.assertEqual(rc, 0, f"healthy server rejected:\n{out}")
        for step in ("tcp", "liveness", "initialize", "tools/list", "GetSystemInfo"):
            self.assertIn(step, out)

    def test_task_prefix_is_stripped_before_use(self):
        """A '[task:...]' prefix is transport metadata; parsing must not trip on it."""
        port = self._serve(MCP, KEY)
        rc, _ = run_verifier(port, "--profile", "vendor",
                             "--expect-marker-file", r"C:\marker.txt")
        self.assertEqual(rc, 0)

    def test_extra_tool_is_detected(self):
        """A leaked Tier-3 tool (Shell) must fail an exact-inventory check."""
        port = self._serve(LEAKY, KEY)
        rc, out = run_verifier(port, "--profile", "vendor")
        self.assertNotEqual(rc, 0, "an inventory with an extra tool must not pass")
        self.assertIn("tools/list", out)

    def test_auth_required_still_fails_a_no_auth_server(self):
        """The old unconditional check must remain available, explicitly asked for.

        Uses a vendor-named server with no auth, so the failure is attributable
        to the auth posture rather than to the tool naming.
        """
        port = self._serve(NOAUTH_MCP, KEY)
        rc, out = run_verifier(port, "--profile", "vendor", "--auth", "required")
        self.assertNotEqual(rc, 0, "--auth required must refuse a server with no auth")
        self.assertIn("liveness", out)


class RigGatewayProfileTests(unittest.TestCase):
    """The rig-gateway profile: no auth by default, lowercase tool names.

    The bug: the verifier demanded 401/403 unconditionally and hard-coded vendor
    tool names, so it failed against rig-gateway -- the very server it ships
    with. A verifier that always reports red is as useless as one that always
    reports green, and this suite pins both directions.
    """

    def setUp(self):
        self._servers: list[subprocess.Popen] = []
        self.port = free_port()
        proc = spawn(RIG_MCP, self.port)
        self._servers.append(proc)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.4):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            self.fail("rig-gateway fake never started")

    def tearDown(self):
        for proc in self._servers:
            proc.kill()
            proc.wait()
        time.sleep(0.4)

    def test_no_auth_server_passes_with_auth_none(self):
        rc, out = run_verifier(self.port, "--auth", "none")
        self.assertEqual(rc, 0, f"rig-gateway profile rejected its own server:\n{out}")
        for step in ("tcp", "liveness", "initialize", "tools/list", "system_info"):
            self.assertIn(step, out)
        self.assertIn('"hostname": "RIG-FAKE"', out)
        self.assertIn('"sandbox_root": "(unset)"', out)

    def test_no_auth_server_fails_with_auth_required(self):
        """Asking for auth that is not there must not pass silently."""
        rc, out = run_verifier(self.port, "--auth", "required")
        self.assertNotEqual(rc, 0)
        self.assertIn("liveness", out)

    def test_hostname_must_match_the_complete_field(self):
        rc, out = run_verifier(self.port, "--auth", "none", "--expect-hostname", "RIG")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("[FAIL] identity", out)

    def test_marker_read_uses_the_rig_gateway_tool_name(self):
        rc, out = run_verifier(self.port, "--auth", "none",
                               "--expect-marker-file", r"C:\marker.txt")
        self.assertEqual(rc, 0, out)
        self.assertIn("identity", out)

    def test_extra_tier_tool_is_detected(self):
        """Enabling tier 2 without meaning to must fail the inventory check."""
        port = free_port()
        proc = spawn(RIG_LEAKY, port)
        self._servers.append(proc)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                    break
            except OSError:
                time.sleep(0.2)
        rc, out = run_verifier(port, "--auth", "none")
        self.assertNotEqual(rc, 0, "a write tool present must not pass a tier-1 check")
        self.assertIn("tools/list", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
