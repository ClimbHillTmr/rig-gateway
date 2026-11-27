"""Repair a port-only change for one existing anonymous Codex HTTP registration."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import ipaddress
import json
from pathlib import Path, PureWindowsPath
import re
import sys
from urllib.parse import urlsplit

from verify_endpoint import Mcp, RIG_GATEWAY_TOOLS, RIG_TIER2_TOOLS, RIG_TIER3_TOOLS


class RepairError(Exception):
    pass


@asynccontextmanager
async def codex_connection():
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server", "--stdio", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=16 * 1024 * 1024,
    )
    sequence = 0

    async def request(method, params):
        nonlocal sequence
        sequence += 1
        message = {"id": sequence, "method": method, "params": params}
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        await proc.stdin.drain()
        while line := await proc.stdout.readline():
            response = json.loads(line)
            if response.get("id") == sequence:
                if "error" in response:
                    raise RepairError(f"Codex rejected {method}. Check version or configuration conflict.")
                return response["result"]
        raise RepairError(f"Codex disconnected during {method}.")

    async def rpc(method, params):
        try:
            return await asyncio.wait_for(request(method, params), 60)
        except asyncio.TimeoutError as exc:
            raise RepairError(f"Codex timed out during {method}.") from exc

    try:
        await rpc("initialize", {"clientInfo": {"name": "rig-repair", "version": "1"},
                                 "capabilities": {"experimentalApi": True}})
        proc.stdin.write(b'{"method":"initialized"}\n')
        await proc.stdin.drain()
        yield rpc
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def registration(rpc, name):
    state = await rpc("config/read", {"cwd": str(Path.cwd()), "includeLayers": True})
    layers = [layer for layer in state["layers"] if layer["name"]["type"] == "user"
              and not layer["name"].get("profile") and not layer.get("disabledReason")]
    if len(layers) != 1:
        raise RepairError("Cannot identify the writable user configuration.")
    layer = layers[0]
    key = f"mcp_servers.{name}.url"
    origin = state["origins"].get(key, {})
    local = layer["config"].get("mcp_servers", {}).get(name, {})
    entry = state["config"].get("mcp_servers", {}).get(name, {})
    if (origin.get("name") != layer["name"] or not local.get("url")
            or entry.get("url") != local["url"] or not entry.get("enabled", True)):
        raise RepairError("Expected an enabled HTTP URL owned by the base user configuration.")
    allowed = {"url", "enabled", "environment_id", "tool_timeout_sec", "startup_timeout_sec",
               "enabled_tools", "disabled_tools", "required"}
    if ((local.keys() | entry.keys()) - allowed or entry.get("environment_id", "local") != "local"):
        raise RepairError("Repair supports local anonymous entries with standard filters and timeouts.")
    return layer, entry


def check_endpoint(args, tools):
    client = Mcp(str(args.host), args.port, "", 30)
    init = client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "rig-repair", "version": "1"}})
    if init.get("serverInfo", {}).get("name") != "rig-gateway":
        raise RepairError("Unexpected MCP server identity.")
    client.protocol = init["protocolVersion"]
    client.notify("notifications/initialized")
    listing = client.rpc("tools/list")
    if listing.get("nextCursor") or sorted(t["name"] for t in listing["tools"]) != sorted(tools):
        raise RepairError("Gateway tool inventory differs from the approved tier.")
    info = json.loads(client.call("system_info", {}))
    if info["hostname"].casefold() != args.expect_hostname.casefold():
        raise RepairError("Windows hostname differs from the deployment record.")
    policy = json.loads(client.call("host_status", {}))["policy"]
    root = policy["sandbox_root"]
    if args.expect_sandbox == "unset":
        matches = (args.tier == 1 and policy["writes_confined_to_root"] is False
                   and root == "(unset -- all writes will be refused)")
    else:
        matches = (policy["writes_confined_to_root"] is True
                   and PureWindowsPath(root) == PureWindowsPath(args.expect_sandbox))
    if not matches:
        raise RepairError("Sandbox or write confinement differs from the deployment record.")


async def write_url(rpc, layer, key, url):
    return await rpc("config/value/write", {"filePath": layer["name"]["file"],
                     "expectedVersion": layer["version"], "keyPath": key,
                     "value": url, "mergeStrategy": "replace"})


async def repair(args):
    name = args.codex_entry
    inventory = set((RIG_GATEWAY_TOOLS, RIG_TIER2_TOOLS, RIG_TIER3_TOOLS)[args.tier - 1].split(","))
    key = f"mcp_servers.{name}.url"
    async with codex_connection() as rpc:
        layer, entry = await registration(rpc, name)
        filtered = inventory.intersection(entry.get("enabled_tools", inventory))
        filtered.difference_update(entry.get("disabled_tools", []))
        if not {"system_info", "host_status"} <= filtered:
            raise RepairError("Client filters must permit both read-only identity and policy checks.")
        old = entry["url"]
        parts = urlsplit(old)
        if (parts.scheme != "http" or parts.hostname != str(args.host)
                or parts.path != "/mcp" or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or old != f"http://{parts.netloc}/mcp"):
            raise RepairError("Saved URL must match the deployment's direct HTTP address and /mcp path.")
        url = old if (parts.port or 80) == args.port else f"http://{args.host}:{args.port}/mcp"
        await asyncio.to_thread(check_endpoint, args, inventory)
        print("Verified deployed gateway, Windows hostname, exact tier and sandbox.", flush=True)
        expected = deepcopy(layer["config"])
        expected["mcp_servers"][name]["url"] = url
        written = None
        if old != url:
            # If the reply is lost, the commit state is unknown. Never issue a blind retry.
            print(f"Updating only {key} ({parts.port or 80} -> {args.port}).", flush=True)
            try:
                written = await write_url(rpc, layer, key, url)
            except (RepairError, OSError) as exc:
                raise RepairError(f"{exc} Read the saved URL before retrying.") from exc
        try:
            if written and written["status"] != "ok":
                raise RepairError("URL write was overridden.")
            async with codex_connection() as fresh:
                current, effective = await registration(fresh, name)
                if current["config"] != expected or effective != {**entry, "url": url}:
                    raise RepairError("Unexpected configuration difference after reopening Codex.")
                result = await fresh("mcpServerStatus/list", {"serverName": name, "detail": "toolsAndAuthOnly"})
                entries = result["data"]
                if (result.get("nextCursor") or len(entries) != 1 or entries[0]["name"] != name
                        or entries[0].get("toolsError") or set(entries[0]["tools"]) != filtered):
                    raise RepairError("Fresh Codex connection did not discover the expected tools.")
                await asyncio.to_thread(check_endpoint, args, inventory)
            # config/read can cache a layer for the lifetime of an app-server.
            async with codex_connection() as audit:
                final, final_entry = await registration(audit, name)
                if final["version"] != current["version"] or final_entry != effective:
                    raise RepairError("Configuration changed during verification.")
        except (Exception, SystemExit):
            if written:
                print("Verification failed. Attempting version-guarded URL rollback.", file=sys.stderr)
                try:
                    receipt = await write_url(rpc, {"name": layer["name"], "version": written["version"]}, key, old)
                except (RepairError, OSError) as exc:
                    raise RepairError("Rollback unconfirmed. Recheck the saved URL and concurrent edits.") from exc
                if receipt["status"] != "ok":
                    raise RepairError("Rollback was overridden. Check the effective entry.")
                print("Restored the previous URL.", file=sys.stderr)
            raise
    action = "Updated URL" if written else "URL already correct"
    print(f"{action}. Fresh Codex connection discovered {len(filtered)} tools. Identity and policy reverified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-entry", required=True)
    parser.add_argument("--host", type=ipaddress.IPv4Address, required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--expect-hostname", required=True)
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--expect-sandbox", required=True, help="Approved absolute Windows path, or unset for Tier 1")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.codex_entry) or not 1 <= args.port <= 65535:
        parser.error("Invalid Codex entry name or deployment port.")
    root = PureWindowsPath(args.expect_sandbox)
    if not ((args.expect_sandbox == "unset" and args.tier == 1)
            or (root.is_absolute() and ".." not in root.parts)):
        parser.error("Supply the expected absolute sandbox path, or unset for Tier 1.")
    try:
        asyncio.run(repair(args))
    except (RepairError, OSError) as exc:
        parser.exit(1, f"Repair failed: {exc}\n")
    except (ValueError, KeyError, TypeError, AttributeError):
        parser.exit(1, "Repair failed: unsupported configuration or malformed protocol response.\n")


if __name__ == "__main__":
    main()
