"""Write a verified host handoff or register its endpoint on a Windows client."""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import tempfile

from repair_codex import (RepairError, RIG_GATEWAY_TOOLS, RIG_TIER2_TOOLS, RIG_TIER3_TOOLS,
                          check_endpoint, codex_connection, inspect_policy, repair, write_url)


def settings(record):
    host = ipaddress.IPv4Address(record["host"])
    if host not in ipaddress.IPv4Network("100.64.0.0/10"):
        raise ValueError("Expected a Tailscale IPv4 address from the host.")
    port, tier, name = record["port"], record["tier"], record["hostname"]
    if type(port) is not int or not 1 <= port <= 65535 or type(tier) is not int or tier not in (1, 2, 3):
        raise ValueError("Invalid deployment port or tier.")
    if not isinstance(name, str) or not re.fullmatch(r"[\w.-]{1,253}", name):
        raise ValueError("Invalid Windows hostname.")
    return argparse.Namespace(host=host, port=port, tier=tier, expect_hostname=name, codex_entry="rig-gateway")


def inventory(args):
    return (RIG_GATEWAY_TOOLS, RIG_TIER2_TOOLS, RIG_TIER3_TOOLS)[args.tier - 1].split(",")


def export_record(path, args):
    policy = inspect_policy(args, inventory(args))
    sandbox = policy["sandbox_root"]
    if not policy["writes_confined_to_root"]:
        if args.tier != 1 or sandbox != "(unset -- all writes will be refused)":
            raise ValueError("Unexpected deployment sandbox policy.")
        sandbox = "unset"
    elif not PureWindowsPath(sandbox).is_absolute():
        raise ValueError("Expected an absolute sandbox path.")
    record = dict(host=str(args.host), port=args.port, tier=args.tier, hostname=args.expect_hostname, sandbox=sandbox)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as tmp:
        tmp.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    try:
        os.replace(tmp.name, path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


async def connect_codex(args, url):
    async with codex_connection() as rpc:
        state = await rpc("config/read", {"cwd": str(Path.cwd()), "includeLayers": True})
        if args.codex_entry not in state["config"].get("mcp_servers", {}):
            layers = [layer for layer in state["layers"] if layer["name"]["type"] == "user"
                      and not layer["name"].get("profile") and not layer.get("disabledReason")]
            if len(layers) != 1 or args.codex_entry in layers[0]["config"].get("mcp_servers", {}):
                raise RepairError("Cannot identify an available user entry.")
            result = await write_url(rpc, layers[0], "mcp_servers.rig-gateway.url", url)
            if result["status"] != "ok":
                raise RepairError("Codex registration was overridden.")
    await repair(args)


def connect_claude(args, url):
    exe = shutil.which("claude")
    if not exe:
        raise ValueError("Claude Code is missing from PATH.")
    def cli(*argv):
        return subprocess.run([exe, "mcp", *argv], capture_output=True, timeout=90,
                              encoding="utf-8", errors="replace")
    info = cli("get", args.codex_entry)
    if info.returncode and re.search(r"No MCP server (?:found|named)", info.stdout + info.stderr):
        if cli("add", "--scope", "user", "--transport", "http", args.codex_entry, url).returncode:
            raise ValueError("Claude Code could not create the user entry.")
        info = cli("get", args.codex_entry)
    if (info.returncode or not re.search(r"(?m)^\s*URL:\s*" + re.escape(url) + r"\s*$", info.stdout)
            or not re.search(r"(?im)^\s*Status:.*\bConnected\b", info.stdout)):
        raise ValueError("Claude Code did not confirm a connected entry at this URL. Check 'claude mcp get rig-gateway'.")
    print("Claude Code confirmed Connected at the verified URL.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    commands = parser.add_subparsers(dest="mode", required=True)
    export = commands.add_parser("export")
    export.add_argument("host")
    export.add_argument("port", type=int)
    export.add_argument("tier", type=int)
    export.add_argument("hostname")
    commands.add_parser("Codex")
    commands.add_parser("Claude")
    options = parser.parse_args()
    if options.mode == "export":
        export_record(options.record, settings(vars(options)))
        return
    record = json.loads(options.record.read_text(encoding="utf-8-sig"))
    args = settings(record)
    args.expect_sandbox = record["sandbox"]
    check_endpoint(args, inventory(args))
    url = f"http://{args.host}:{args.port}/mcp"
    if options.mode == "Codex":
        asyncio.run(connect_codex(args, url))
    else:
        connect_claude(args, url)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, TypeError, RepairError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Setup failed: {exc}")
