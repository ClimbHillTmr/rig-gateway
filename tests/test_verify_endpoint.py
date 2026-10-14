"""Negative tests: the verifier must reject things that merely look healthy."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
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

EXTRA_TOOLS = ["GetSystemInfo", "ListProcesses", "FileList", "FileRead"]


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


class VerifierTests(unittest.TestCase):
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
        rc, _ = run_verifier(free_port())
        self.assertNotEqual(rc, 0)

    def test_starved_listener_is_rejected(self):
        """The regression guard: a socket that accepts but never answers must FAIL."""
        port = self._serve(STARVED)
        rc, out = run_verifier(port)
        self.assertNotEqual(rc, 0, "a listening-but-silent server must not pass")
        self.assertIn("liveness", out)

    def test_healthy_server_passes_all_checks(self):
        port = self._serve(MCP, KEY)
        rc, out = run_verifier(port)
        self.assertEqual(rc, 0, f"healthy server rejected:\n{out}")
        for step in ("tcp", "liveness", "initialize", "tools/list", "GetSystemInfo"):
            self.assertIn(step, out)

    def test_task_prefix_is_stripped_before_use(self):
        """A '[task:...]' prefix is transport metadata; parsing must not trip on it."""
        port = self._serve(MCP, KEY)
        rc, _ = run_verifier(port, "--expect-marker-file", r"C:\marker.txt")
        self.assertEqual(rc, 0)

    def test_extra_tool_is_detected(self):
        """A leaked Tier-3 tool (Shell) must fail an exact-inventory check."""
        port = self._serve(LEAKY, KEY)
        rc, out = run_verifier(port)
        self.assertNotEqual(rc, 0, "an inventory with an extra tool must not pass")
        self.assertIn("tools/list", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)