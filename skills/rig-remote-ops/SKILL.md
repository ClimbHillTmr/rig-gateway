---
name: rig-remote-ops
description: Operate a remote Windows machine from an AI agent over a private tailnet, using the rig-gateway MCP server. Use when asked to connect to, reach, inspect, or operate a remote Windows host; to replace a vendor remote-desktop MCP (AweSun/向日葵, AnyDesk, TeamViewer) with a self-hosted one; or when an MCP endpoint over Tailscale times out, hangs, or accepts TCP but never answers HTTP. Covers tiered tool enablement, the single-root write sandbox, hidden credential handling, the eight-step verification ladder, and the output-starvation failure that makes a "listening" server look dead.
---

# Remote Windows ops over a tailnet

Bring up and drive a remote Windows host as an MCP endpoint, and verify the channel
honestly before trusting it.

## Default posture: read-only, smallest useful tier

`rig-gateway` ships 15 tools in three tiers. **Only tier 1 is on by default.**

| Tier | Tools | Enable with |
|---|---|---|
| 1 — read | `host_status` `system_info` `list_processes` `list_directory` `read_file` | (default) |
| 2 — mutate | + `capture_screen` `write_file` `make_directory` `move_path` `delete_path` `transfer_in` `transfer_out` | `--enable-tier2` |
| 3 — act | + `run_command` `type_text` `press_keys` | `--enable-tier3` **and** `RIG_ALLOW_TIER3=1` |

Tier 3 takes **two** independent keys on purpose. Those tools can reach the target's real
control software — anything they drive inherits physical consequences. A client that
enables them by accident is exactly the failure this design exists to prevent.

Ask before enabling tier 2 or 3, every time. Enabling them is a decision about someone
else's machine, not a configuration tweak.

## The write sandbox

All mutations are confined to `RIG_SANDBOX_ROOT`; reads are unrestricted, because a
diagnostic channel that cannot read the thing it is diagnosing is useless.

- The check is **component-wise containment**. `C:\rootX` is outside `C:\root` even though
  it starts with those characters. Never "simplify" this to a `startswith` test.
- An unset `RIG_SANDBOX_ROOT` refuses every write. That is fail-closed by design.
- Existing files are not overwritten without `RIG_ALLOW_OVERWRITE=1`.
- Directory deletion needs an explicit `recursive=True`.

Report `host_status().policy` rather than claiming safety in prose — it states the live
boundary instead of restating the design.

## Credentials

The tailnet carries the transport; there is no vendor account in the path and no token
that can expire unnoticed. If you put the server behind HTTP, auth is yours to provide —
the server deliberately ships without one, so the auth story stays explicit rather than
becoming a silent default. Never put a secret on a command line or in a repo.

## Verification: trust nothing that looks green

The defining failure in this setup is a server that **looks healthy and serves nothing**.
Work up this ladder; each step proves something the previous one did not.

| # | Check | What passing actually proves |
|---|---|---|
| 1 | `tailscale ping <host>` | a route exists (relay or direct — relay is fine) |
| 2 | TCP connect | a socket is listening. **Not** that HTTP works |
| 3 | `GET /health` returns a status | the application is answering |
| 4 | unauthenticated `POST /mcp` → `401`/`403` | auth is enforced |
| 5 | authenticated `initialize` → `200` | the key is right; handshake works |
| 6 | `tools/list` equals the allowlist **exactly** | nothing extra leaked in |
| 7 | one real `tools/call` returns content | tools execute, not merely list |
| 8 | read a marker file you placed | you reached the intended host and path |

`scripts/verify_endpoint.py` runs all eight and exits non-zero at the first unproven step:

```bash
python scripts/verify_endpoint.py --host 100.64.0.1 --port 8099 \
    --expect-marker-file 'C:\approved\root\channel-marker.txt'
```

### Three measurement traps

- **A listening port is not a responding server.** Checks 2 and 3 catch different failures;
  never let one stand in for the other.
- **Any HTTP status proves liveness.** With an IP allowlist configured, a self-request may
  legitimately be refused. Demanding `200` there turns a healthy server into a "failure".
- **Verify identity with something the host actually returns.** If the tool does not expose
  a hostname, do not assert on a hostname — read back a marker file you planted. An
  assertion on a field the tool never returns fails on a perfect server.

Read a tool's implementation before asserting on its output. Return shapes, prefixes and
field names are the top cause of "the check failed but everything works".

## Failure modes worth recognising

### Port is listening, every HTTP request times out

**Output starvation** — the most common way this channel dies silently. Two independent
causes, both on the serving side:

1. **Undrained stdout pipe.** Starting the server with stdout/stderr redirected and nothing
   ever reading it blocks the process permanently once the ~64 KB pipe buffer fills. Every
   HTTP request writes an access-log line, so this triggers in ordinary use. It presents
   identically to a network fault. **Fix: do not redirect.** Let the child inherit the
   console handles; if you must capture output, drain it continuously to a file from a
   background thread.
2. **Console QuickEdit.** A user click-dragging text in the console stops the console
   servicing its handle and the server blocks on its next write. **Fix:** clear
   `ENABLE_QUICK_EDIT_MODE` before starting the child, and tell operators never to select
   text in that window.

Prove the fix with a **negative** test: serve an endpoint that emits far more than the pipe
buffer, drive sustained requests, and assert the server answers in both modes. A test that
only proves "it responded" cannot kill this bug.

### Config disagrees with the running server

An explicit `--tools` flag overrides the config file. Read the actual command line, and
confirm with `tools/list` rather than by reading your own config back.

### Tool results carry injected metadata

Servers that wrap tools in a task manager prepend a run id to successful text results,
e.g. `[task:1d74426ef23c] <real output>`. That is transport metadata, not payload. Strip
exactly one anchored prefix before parsing, and never more than one. A parser choking on
line one is usually reading the prefix — and reporting a confusing "syntax error".

## Honest reporting

State what each check proved, and name what stayed unverified. Overclaims to avoid:

- "Connected" when only TCP succeeded.
- "Verified the right host" when nothing machine-identifying was read back.
- "Replaced the vendor client" when only the read-only tier is enabled.

If a capability is genuinely missing — this gateway cannot reach a locked or disconnected
console, and has no click primitive — say so plainly rather than quietly narrowing the claim.

## Deploying over the internet

Use a mesh VPN (Tailscale / Headscale / Netbird). No inbound ports on the target's router.
The tailnet encrypts the transport; a relayed path is slower but equivalent, and is **not**
a failure. Keep the existing vendor client until the replacement is verified end to end —
including one real file transfer and one screenshot — not merely reachable.