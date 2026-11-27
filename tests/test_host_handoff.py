"""Check the Tier 1 handoff from the same console-less environment as a login task."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


def test_export_from_detached_host(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "skills/rig-remote-ops/scripts"))
    from setup_connection import export_record

    monkeypatch.delenv("RIG_SANDBOX_ROOT", raising=False)
    monkeypatch.delenv("RIG_SELF_CHECK_URL", raising=False)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    args = argparse.Namespace(host="127.0.0.1", port=port, tier=1, expect_hostname=socket.gethostname())
    record = tmp_path / "rig-connection.json"
    detached = "import sys,runpy; sys.stdout=sys.stderr=None; runpy.run_module('rig_gateway.server',run_name='__main__')"
    proc = subprocess.Popen([sys.executable, "-c", detached, "--transport", "streamable-http",
                             "--host", args.host, "--port", str(port)], cwd=root)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert proc.poll() is None, "Detached gateway exited before listening"
            try:
                with socket.create_connection((args.host, port), .5):
                    break
            except OSError:
                time.sleep(.1)
        export_record(record, args)
        assert json.loads(record.read_text()) == {
            "host": args.host, "port": port, "tier": 1, "hostname": args.expect_hostname, "sandbox": "unset"
        }
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)
