"""Exercise port repair against a disposable Codex home and a loopback MCP server."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/rig-remote-ops/scripts/repair_codex.py"
NAMES = ["host_status", "system_info", "list_processes", "list_directory", "read_file"]


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = req["method"]
        if method == "initialize":
            result = {"protocolVersion": req["params"]["protocolVersion"],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": self.server.identity, "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": n, "inputSchema": {"type": "object"}}
                                for n in self.server.inventory]}
        elif method == "tools/call":
            tool = req["params"]["name"]
            self.server.calls.append(tool)
            if tool == "system_info":
                data = {"hostname": self.server.hostname}
            elif tool == "host_status":
                data = {"policy": {"sandbox_root": "C:\\test", "writes_confined_to_root": True}}
                self.server.on_policy()
            else:
                raise AssertionError(tool)
            result = {"content": [{"type": "text", "text": json.dumps(data)}]}
        elif "id" not in req:
            self.send_response(202)
            self.end_headers()
            return
        else:
            self.send_error(404)
            return
        body = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(shutil.which("codex"), "requires the Codex CLI")
class RepairTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def setup_config(self, tmp_path):
        self.config = tmp_path / "config.toml"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        self.addCleanup(self.server.server_close)
        self.server.identity = "rig-gateway"
        self.server.hostname = "TEST-RIG"
        self.server.inventory = NAMES[:]
        self.server.calls = []
        self.server.on_policy = lambda: None
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        self.old = '[mcp_servers.rig-gateway]\nurl = "http://127.0.0.1:1/mcp" # endpoint\ntool_timeout_sec = 20\n\n[mcp_servers.other]\ncommand = "unused"\nargs = []\nenabled = false\n'
        self.config.write_text(self.old, encoding="utf-8")

    def invoke(self, sandbox="C:\\test"):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--codex-entry", "rig-gateway",
             "--host", "127.0.0.1", "--port", str(self.port), "--tier", "1",
             "--expect-hostname", "TEST-RIG", "--expect-sandbox", sandbox],
            env=dict(os.environ, CODEX_HOME=str(self.config.parent)), cwd=self.config.parent.parent,
            capture_output=True, text=True, timeout=100,
        )

    def test_change_then_noop(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.config.read_text(), self.old.replace(":1/mcp", f":{self.port}/mcp"))
        stamp = self.config.stat().st_mtime_ns
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(self.config.stat().st_mtime_ns, stamp)
        self.assertEqual(self.server.calls, ["system_info", "host_status"] * 4)

    def test_reject_mismatches_before_write(self):
        for attr, value in (("identity", "other"), ("inventory", ["host_status"]), ("hostname", "other")):
            with self.subTest(attr=attr):
                before = getattr(self.server, attr)
                setattr(self.server, attr, value)
                self.assertNotEqual(self.invoke().returncode, 0)
                setattr(self.server, attr, before)
                self.assertEqual(self.config.read_text(), self.old)
        self.assertNotEqual(self.invoke("C:\\wrong").returncode, 0)
        self.assertEqual(self.config.read_text(), self.old)

    def test_filter_preserved(self):
        filtered = self.old.replace("tool_timeout_sec", 'disabled_tools = ["read_file"]\ntool_timeout_sec')
        self.config.write_text(filtered)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.config.read_text(), filtered.replace(":1/mcp", f":{self.port}/mcp"))

    def test_rollback_cannot_overwrite_later_edit(self):
        def concurrent_edit():
            if self.server.calls.count("host_status") == 2:
                with self.config.open("a") as f:
                    f.write("startup_timeout_sec = 35\n")

        self.server.on_policy = concurrent_edit
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        expected = self.old.replace(":1/mcp", f":{self.port}/mcp") + "startup_timeout_sec = 35\n"
        self.assertEqual(self.config.read_text(), expected)

    def test_filter_blocks_required_check(self):
        initial = self.old.replace("tool_timeout_sec", 'disabled_tools = ["host_status"]\ntool_timeout_sec')
        self.config.write_text(initial)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.config.read_text(), initial)

    def test_credentials_rejected(self):
        initial = self.old.replace("tool_timeout_sec", 'bearer_token_env_var = "EXAMPLE"\ntool_timeout_sec')
        self.config.write_text(initial)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.config.read_text(), initial)

    def test_concurrent_edit_blocks_write(self):
        changed = self.old + "\nstartup_timeout_sec = 35\n"
        self.server.on_policy = lambda: self.config.write_text(changed)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.config.read_text(), changed)
        self.assertEqual(self.server.calls, ["system_info", "host_status"])

    def test_changed_policy_after_write_rolls_back(self):
        self.server.on_policy = lambda: setattr(self.server, "hostname", "other")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restored the previous URL", result.stderr)
        self.assertEqual(self.config.read_text(), self.old)
