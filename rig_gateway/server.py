"""rig-gateway — MCP server exposing a remote Windows host over a tailnet.

Replaces a vendor-hosted remote-desktop MCP with a self-hosted one: no third-party
client resident, no cloud account mediating the session, no silently-expiring token.

Capability tiers mirror what a remote-operations agent actually needs, and the
default is the smallest useful one:

  tier1 (default)  status, system info, process list, directory listing, file read
  tier2 (opt-in)    screenshot, file write/transfer, directory create/rename/delete
  tier3 (opt-in)    command execution, keystroke injection

Writes are confined to a single configured root (RIG_SANDBOX_ROOT) by
``pathpolicy``; keystroke and command tiers are refused entirely unless the
operator both enables them and sets RIG_ALLOW_TIER3=1, because they are the
tools that can reach a machine's real control software.

Tool annotations carry the same tier information, so a client can show the risk
before the operator clicks.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore

from .pathpolicy import (
    PathDenied,
    active_root,
    describe_policy,
    resolve_read_path,
    resolve_write_path,
)

TIER1 = {"host_status", "list_processes", "system_info", "list_directory", "read_file"}
TIER2 = TIER1 | {"capture_screen", "write_file", "delete_path", "make_directory", "move_path",
                 "transfer_out", "transfer_in"}
TIER3 = TIER2 | {"run_command", "type_text", "press_keys"}

mcp = FastMCP("rig-gateway")


def _tool_error_base() -> type[BaseException]:
    """The SDK's anticipated-failure exception, if this version has one.

    The MCP SDK deliberately scrubs the text of a *crash*: the client sees only
    "Error executing tool <name>". Only the SDK's own ToolError keeps its message.
    A policy refusal is the most important thing an operator can be told, so
    ``Denied`` inherits from whichever class preserves it -- otherwise "refused
    by the sandbox" is indistinguishable from "the server is broken", which is
    the confusion this project exists to remove.
    """
    for module, name in (
        ("mcp.server.mcpserver.exceptions", "ToolError"),   # mcp 2.x
        ("mcp.server.fastmcp.exceptions", "ToolError"),     # mcp 1.x
        ("mcp.server.lowlevel.server", "ToolError"),
    ):
        try:
            return getattr(__import__(module, fromlist=[name]), name)
        except (ImportError, AttributeError):
            continue
    return PermissionError  # no SDK present; still a clear error locally


_ToolError = _tool_error_base()

# When no SDK is present the base is already PermissionError, and naming it
# twice is a TypeError at class-creation time -- which would take out the whole
# module, not just the missing-SDK path. Build the bases without the duplicate.
_DeniedBases = (_ToolError,) if _ToolError is PermissionError else (_ToolError, PermissionError)


class Denied(*_DeniedBases):
    """A request was refused by policy, with the reason kept in the message.

    Inherits the SDK's anticipated-failure class so the text survives to the
    client, and PermissionError so callers that reason in stdlib terms still
    catch it.
    """


def _require_tier3(what: str) -> None:
    if os.environ.get("RIG_ALLOW_TIER3", "").strip() not in ("1", "true", "yes"):
        raise Denied(
            f"{what} is in tier 3 and is refused: it can reach the target machine's control "
            "software. Set RIG_ALLOW_TIER3=1 on the server AND pass --enable-tier3 to the "
            "client only when the machine's owner has authorised it.")


def _write(path: str) -> str:
    """Every mutating path goes through here. Call it immediately before acting."""
    try:
        return resolve_write_path(path)
    except PathDenied as exc:
        raise Denied(str(exc)) from exc


# --------------------------------------------------------------------------- tier 1

@mcp.tool()
def host_status() -> dict:
    """Connectivity and policy self-report. Read-only.

    Distinguishes three things callers routinely conflate: is the route up, is
    the socket open, and is the application actually answering. Only the last one
    means the server works.
    """
    import socket
    import urllib.error
    import urllib.request

    from urllib.parse import urlsplit

    result: dict[str, Any] = {"policy": describe_policy()}
    target = os.environ.get("RIG_SELF_CHECK_URL", "").strip()
    if not target:
        result["note"] = "set RIG_SELF_CHECK_URL to enable the liveness probe"
        return result

    # Parse with urlsplit, not partition(":"). The documented value is the MCP
    # endpoint ("http://host:8099/mcp"), and a naive split turns the path into
    # part of the port -- int("8099/mcp") raises ValueError, so the one tool
    # whose whole job is to report on connectivity crashed on its own example.
    # A bare "host:port" is accepted too; urlsplit reads it as scheme="host".
    try:
        parts = urlsplit(target if "://" in target else "http://" + target)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not host:
            raise ValueError("no host component")
    except ValueError as exc:
        result["parse_error"] = f"RIG_SELF_CHECK_URL={target!r} is not a usable URL: {exc}"
        result["tcp_open"] = False
        result["http_proves"] = "NOTHING -- the probe URL could not be parsed"
        return result

    tcp = False
    try:
        with socket.create_connection((host, port), timeout=5):
            tcp = True
    except OSError as exc:
        result["tcp_error"] = str(exc)
    result["tcp_open"] = tcp
    result["tcp_proves"] = "only that something is listening"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(target, timeout=5) as resp:
            result["http_status"] = resp.status
            result["http_proves"] = "the application is answering"
    except urllib.error.HTTPError as exc:
        # Any status is proof of life. An allowlist may legitimately refuse us.
        result["http_status"] = exc.code
        result["http_proves"] = "the application is answering (a refusal is still a response)"
    except Exception as exc:  # noqa: BLE001
        result["http_error"] = str(exc)
        result["http_proves"] = "NOTHING -- a listening socket with no HTTP response is the " \
                                "output-starvation signature, not a healthy server"
    return result


@mcp.tool()
def system_info() -> dict:
    """OS, CPU, memory, disk and uptime of the host. Read-only."""
    import platform

    import psutil

    boot = psutil.boot_time()
    return {
        "system": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "hostname": platform.node(),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_cores": psutil.cpu_count(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("C:\\").percent if platform.system() == "Windows" else None,
        "uptime_seconds": int(time.time() - boot),
        "sandbox_root": active_root() or "(unset)",
    }


@mcp.tool()
def list_processes(limit: int = 25, sort_by: str = "memory") -> dict:
    """Running processes, heaviest first. Read-only. sort_by: memory|cpu|name."""
    import psutil

    procs = []
    for proc in psutil.process_iter(["pid", "name", "username", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            procs.append({
                "pid": info["pid"], "name": info["name"],
                "username": info.get("username"),
                "memory_mb": round((info["memory_info"].rss or 0) / 1048576, 1),
                "cpu_percent": info.get("cpu_percent"),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = {"memory": lambda p: -p["memory_mb"], "cpu": lambda p: -(p["cpu_percent"] or 0),
           "name": lambda p: p["name"].lower()}.get(sort_by, lambda p: -p["memory_mb"])
    return {"total": len(procs), "returned": min(limit, len(procs)), "processes": sorted(procs, key=key)[:limit]}


@mcp.tool()
def list_directory(path: str = "C:\\", show_hidden: bool = False) -> dict:
    """List a remote directory. Read-only; not restricted to the sandbox root."""
    target = resolve_read_path(path)
    import os as _os

    if not _os.path.isdir(target):
        return {"path": target, "exists": False,
                "note": "not a directory. Check the parent listing -- some servers return an "
                        "empty result rather than an error for a missing path."}
    entries = []
    for name in _os.listdir(target):
        if not show_hidden and name.startswith("."):
            continue
        full = _os.path.join(target, name)
        try:
            st = _os.stat(full)
            entries.append({"name": name, "is_dir": _os.path.isdir(full), "size": st.st_size,
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
        except OSError:
            entries.append({"name": name, "is_dir": None, "error": "stat failed (permissions)"})
    return {"path": target, "count": len(entries), "entries": entries}


@mcp.tool()
def read_file(path: str, encoding: str = "utf-8", max_chars: int = 100_000) -> dict:
    """Read a remote text file. Read-only, unrestricted.

    Returns base64 when ``encoding='binary'``. A file that is not there is
    reported as such -- never as an empty success, which is indistinguishable
    from an empty file.
    """
    from pathlib import Path

    target = resolve_read_path(path)
    p = Path(target)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {target}")
    if encoding == "binary":
        return {"path": target, "encoding": "base64", "content": base64.b64encode(p.read_bytes()).decode()}
    text = p.read_text(encoding=encoding, errors="replace")
    truncated = len(text) > max_chars
    return {"path": target, "encoding": encoding, "truncated": truncated,
            "content": text[:max_chars], "chars": len(text)}


# --------------------------------------------------------------------------- tier 2

@mcp.tool()
def capture_screen(quality: int = 70, monitor: int = 1) -> dict:
    """Screenshot the host desktop. Returns base64 JPEG plus the window list.

    **Captures the active display only.** ``monitor`` is validated and reported
    but not yet honoured: multi-monitor capture is unimplemented, so this
    refuses anything but monitor 1 rather than silently returning the primary
    display while appearing to have switched. Pretending to support a parameter
    is how a gap becomes a wrong answer.

    Requires an unlocked, active console session; a locked or disconnected
    session yields a black frame, which is a session problem, not a capture bug.
    """
    if monitor != 1:
        raise Denied(
            f"monitor={monitor} was requested but only the active display is captured. "
            "Multi-monitor capture is not implemented; pass monitor=1 or ask for it "
            "to be added rather than receiving the wrong monitor's frame silently.")
    try:
        import pyautogui
    except ImportError as exc:
        raise Denied(
            "capture_screen needs the 'screen' extra: pip install 'rig-gateway[screen]' "
            f"(missing: {exc.name}).") from exc

    image = pyautogui.screenshot()
    import io

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return {"format": "jpeg", "quality": quality, "monitor": monitor,
            "monitors_supported": 1,
            "size": list(image.size), "image_base64": base64.b64encode(buf.getvalue()).decode()}


@mcp.tool()
def write_file(path: str, content: str, encoding: str = "utf-8", overwrite: bool = False) -> dict:
    """Write a text file. **Confined to the sandbox root.**

    An existing file is refused unless BOTH ``overwrite=True`` is passed here
    and the server was started with ``RIG_ALLOW_OVERWRITE=1``. The two keys are
    deliberate: the caller says "yes, this specific file", the operator says
    "yes, overwriting is allowed on this machine at all".

    ``overwrite`` must be a real parameter -- the docstring used to tell callers
    to pass it while the signature did not accept it, so every client that
    followed the documentation got a TypeError instead of a write.
    """
    resolved = _write(path)
    from pathlib import Path

    p = Path(resolved)
    existed = p.exists()
    if existed:
        operator_ok = os.environ.get("RIG_ALLOW_OVERWRITE", "").lower() in ("1", "true", "yes")
        if not (overwrite and operator_ok):
            raise Denied(
                f"{resolved} already exists. Pass overwrite=True AND start the server "
                f"with RIG_ALLOW_OVERWRITE=1 to replace it "
                f"(overwrite={overwrite}, RIG_ALLOW_OVERWRITE={'set' if operator_ok else 'unset'}).")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return {"path": resolved, "bytes": len(content.encode(encoding)), "overwrote": existed}


@mcp.tool()
def make_directory(path: str) -> dict:
    """Create a directory. **Confined to the sandbox root.** No overwrites."""
    resolved = _write(path)
    import os as _os

    if _os.path.exists(resolved):
        raise Denied(f"{resolved} already exists; refusing to reuse it.")
    _os.makedirs(resolved)
    return {"path": resolved, "created": True}


@mcp.tool()
def move_path(source: str, destination: str) -> dict:
    """Move or rename. **Both endpoints confined to the sandbox root.**"""
    src, dst = _write(source), _write(destination)
    import shutil

    shutil.move(src, dst)
    return {"from": src, "to": dst, "moved": True}


@mcp.tool()
def delete_path(path: str, recursive: bool = False) -> dict:
    """Delete a file or directory. **Confined to the sandbox root.** Irreversible.

    Directories are refused unless ``recursive=True`` is passed explicitly, so a
    stray call cannot take out a tree that merely happens to be non-empty.
    """
    resolved = _write(path)
    import shutil

    p = resolved.rstrip("\\")
    if os.path.isdir(p):
        if not recursive:
            raise Denied(f"{p} is a directory. Pass recursive=True to delete it and its contents.")
        shutil.rmtree(p)
        return {"path": p, "deleted": "directory tree"}
    if not os.path.exists(p):
        raise FileNotFoundError(f"No such path: {p}")
    os.remove(p)
    return {"path": p, "deleted": "file"}


@mcp.tool()
def transfer_out(remote_path: str, local_path: str) -> dict:
    """Copy a file out of the host, into the sandbox. **Destination confined.**

    Both endpoints live on the host: an MCP tool has no access to the client's
    filesystem, so "local" here means the server's own disk. The destination is
    therefore a write like any other and is confined to the sandbox root --
    reading is unrestricted, writing is not, and a copy is a write at one end.
    """
    src = resolve_read_path(remote_path)
    dst = _write(local_path)
    import shutil

    shutil.copy2(src, dst)
    return {"from": src, "to": dst, "bytes": os.path.getsize(dst)}


@mcp.tool()
def transfer_in(local_path: str, remote_path: str) -> dict:
    """Copy a file into the sandbox from elsewhere on the host.

    Same rule as transfer_out, mirrored: the read side is unrestricted, the
    write side is confined to the sandbox root.
    """
    src = resolve_read_path(local_path)
    dst = _write(remote_path)
    import shutil

    shutil.copy2(src, dst)
    return {"from": src, "to": dst, "bytes": os.path.getsize(dst)}


# --------------------------------------------------------------------------- tier 3

@mcp.tool()
def run_command(command: str, timeout_s: int = 60) -> dict:
    """Execute a shell command on the host. **Tier 3 -- can reach anything.**

    Refused unless the operator enabled tier 3 on both ends. This is the tool
    that can drive a machine's real control software; treat every invocation as
    capable of physical side effects.
    """
    _require_tier3("run_command")
    import subprocess

    proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout_s)
    return {"command": command, "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]}


@mcp.tool()
def type_text(text: str) -> dict:
    """Type text into the host's foreground window. **Tier 3.**"""
    _require_tier3("type_text")
    import pyautogui

    pyautogui.typewrite(text, interval=0.02)
    return {"typed": len(text)}


@mcp.tool()
def press_keys(keys: str) -> dict:
    """Press key chords on the host, e.g. 'win,r'. **Tier 3.**"""
    _require_tier3("press_keys")
    import pyautogui

    pyautogui.hotkey(*[k.strip() for k in keys.split(",") if k.strip()])
    return {"pressed": keys}


def build(enable_tier2: bool, enable_tier3: bool) -> FastMCP:
    """Remove the tools the operator did not ask for, so the client cannot call them.

    Removal is one-way: a tool dropped here is not restored by a later call.
    All registrations happen at import, so build() must be called exactly once,
    before run(). Calling it twice with different tiers cannot resurrect a tool.
    """
    enabled = set(TIER1)
    if enable_tier2:
        enabled |= TIER2
    if enable_tier3:
        enabled |= TIER3
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None) if manager else None
    if isinstance(tools, dict):
        for name in [n for n in tools if n not in enabled]:
            tools.pop(name, None)
    return mcp


def resolve_http_binding(run_callable: Any) -> str:
    """Decide how to pass host/port to this FastMCP's run(). Pure; unit-tested.

    Returns "kwargs" if run() accepts host/port -- directly, or (the common case)
    via ``**kwargs``, which is how mcp 2.x MCPServer.run is declared:

        run(self, transport='stdio', **kwargs)

    A literal ``"host" in params`` test misses that and, worse, is *wrong in the
    safe-looking direction*: it falls through to the Settings path, which raises
    on every version whose Settings has no host field, and the server never binds
    at all. That exact bug shipped once -- see tests/test_server_binding.py.

    Returns "settings" only for a version that genuinely takes neither.
    """
    import inspect

    params = inspect.signature(run_callable).parameters
    if "host" in params and "port" in params:
        return "kwargs"
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return "kwargs"
    return "settings"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--enable-tier2", action="store_true",
                    help="screenshot and file mutation tools")
    ap.add_argument("--enable-tier3", action="store_true",
                    help="command execution and keystroke injection (needs RIG_ALLOW_TIER3=1 too)")
    args = ap.parse_args()

    if not active_root():
        print("WARNING: RIG_SANDBOX_ROOT is unset. Reads work; every write will be refused.",
              file=sys.stderr)

    build(args.enable_tier2, args.enable_tier3)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    # FastMCP's API for binding host/port differs across versions. Ask the real
    # signature which form this version takes, and say which path was taken --
    # silently guessing is how a wrong assumption survives to the next user.
    how = resolve_http_binding(mcp.run)
    print(f"binding {args.host}:{args.port} via run({how})", file=sys.stderr)
    if how == "kwargs":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
        return

    # Last resort for a version that accepts neither: set the Settings fields.
    # If that fails, do NOT fall through to run(): it would silently bind
    # 127.0.0.1 instead of the requested address, which looks like a network
    # fault and is not. Fail loudly instead.
    failures = []
    for attr, value in (("host", args.host), ("port", args.port)):
        try:
            setattr(mcp.settings, attr, value)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"settings.{attr} = {value!r}: {exc}")
    if failures:
        raise SystemExit(
            "Cannot bind the requested address with this FastMCP version:\n  "
            + "\n  ".join(failures)
            + "\nPass --host/--port to run(), or pin a FastMCP version that "
              "supports them.")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()