# rig-gateway

A self-hosted MCP server that exposes a remote Windows machine to an AI agent, over a
private tailnet. **Built as a drop-in replacement for vendor remote-desktop MCP servers**
(AweSun / 向日葵, AnyDesk, TeamViewer and friends) on machines where you cannot accept a
third-party client running resident and mediating every session through a vendor cloud.

Two parts, usable together or apart:

- **`rig_gateway/`** — the MCP server. Read-only by default; tiered opt-in for writes,
  screenshots, and command execution.
- **`skills/rig-remote-ops/`** — a Claude Skill encoding the operating discipline: deploy
  order, the verification ladder, and the failures that look green but prove nothing.

---

## Why replace it

| | Vendor remote-desktop MCP | rig-gateway |
|---|---|---|
| Third-party client resident | yes | no |
| Session path | through vendor cloud | your own tailnet |
| Credential that can silently expire | vendor API token | none — yours, on your network |
| Works when the vendor is down or blocked | no | yes |
| What it can do | fixed, vendor-defined | tiered, you choose |
| Write confinement | vendor-specific rule | one configured root, component-checked |
| Audit trail | vendor-side | yours |

The operational argument is the deciding one. A vendor token that expires quietly is
indistinguishable from a machine that went offline, and the fix is not in your hands.

## Honest capability comparison

Against a 17-tool AweSun MCP (session mgmt ×4, file transfer ×8, desktop control ×5):

| Capability | AweSun | rig-gateway | Notes |
|---|---|---|---|
| Session/device status | ✅ | ✅ | |
| File list / read | ✅ | ✅ | |
| File upload / download | ✅ | ✅ | |
| mkdir / rename / delete | ✅ | ✅ | writes need a configured sandbox root |
| Desktop screenshot | ✅ | ✅ | ours is a raw frame; no element annotation |
| Click / type / hotkeys | ✅ | ✅ | tier 3, off by default |
| Run command on target | ✅ | ✅ | tier 3, off by default |
| **Interactive login / unlock** | ✅ | ❌ | **gap** — we cannot type into a locked session |
| **Multi-monitor / virtual display** | ✅ | ⚠️ | ours captures the active display |
| **Vendor SSO / device groups** | ✅ | ❌ | by design |
| Mouse *click* injection | ✅ | ⚠️ | hotkeys and typing only; no click primitive |

Two real gaps worth stating plainly: **we cannot reach a locked or disconnected console**
(the vendor client can reattach a session; we cannot), and **there is no click primitive** —
scripted automation that needs to press a specific pixel is not yet supported.

## Install

```bash
pip install -e .
```

Requires Python ≥ 3.10 and, for the optional tiers, `psutil`, `pillow`, `pyautogui`.

## Run

Read-only, stdio (the usual local-client setup):

```bash
export RIG_SANDBOX_ROOT='C:\approved\directory'   # writes are refused without it
rig-gateway --transport stdio
```

Add screenshot and file mutation:

```bash
rig-gateway --transport stdio --enable-tier2
```

Add command execution and keystrokes — **requires both** the flag and the server env var:

```bash
RIG_ALLOW_TIER3=1 rig-gateway --transport stdio --enable-tier2 --enable-tier3
```

The two-key requirement is deliberate. These are the tools that can reach the target's
real control software; a client that enables them by accident is exactly the failure this
is meant to prevent.

Over HTTP instead:

```bash
rig-gateway --transport streamable-http --host 127.0.0.1 --port 8099
```

Bind to a loopback or tailnet address and put authentication in front of it. This server
has no built-in auth — that is a deliberate choice, so the auth story stays explicit
rather than becoming a silent default.

## Security model

- **Reads are unrestricted.** A diagnostic channel that cannot read the thing it is
  diagnosing is not useful.
- **Every mutation is confined to `RIG_SANDBOX_ROOT`**, checked *component-wise*.
  `C:\rootX` is outside `C:\root`, even though it starts with those characters — a prefix
  test is not containment, and that distinction is enforced by tests.
- **Both ends of a transfer are on the host.** An MCP tool cannot see the client's disk,
  so `transfer_out`/`transfer_in`'s "local" side is the server's own filesystem. The read
  end stays unrestricted; the write end is confined like every other write. (It was not,
  once — a copy could land anywhere the process could write.)
- **Overwriting takes two independent keys**: `overwrite=True` from the caller *and*
  `RIG_ALLOW_OVERWRITE=1` on the server.
- **Directory deletion requires an explicit `recursive=True`**, so a stray call cannot take
  out a non-empty tree by accident.
- **Tier 3 is refused by default**, twice over: the flag and the environment variable.
- `host_status()` reports the live policy instead of asserting safety in prose.

## Verification

The failure that motivates the Skill: a server with no log destination blocks permanently
once the pipe buffer fills. It keeps its listening socket, so TCP still connects and every
HTTP request times out. **A listening port is not a responding server.**

`verify_endpoint.py` walks eight checks — route, TCP, liveness, auth enforcement,
handshake, exact tool inventory, a real tool call, and an identity read-back — and fails at
the first unproven step.

```bash
python verify_endpoint.py --host 100.64.0.1 --port 8099 --auth none \
    --expect-marker-file 'C:\approved\directory\channel-marker.txt'
```

`--auth none` is not a shortcut — it is the honest statement that this server ships
without authentication, and the verifier says so on exit rather than reporting a green
run as if auth had been checked. If you have put auth in front of it, pass
`--auth required` and the check becomes a real one. `--profile vendor` covers the older
`GetSystemInfo`/`FileRead` naming if you are verifying a server you have not replaced yet.

The tests are negative on purpose. `test_starved_listener_is_rejected` reproduces a socket
that accepts and never answers, and asserts the verifier rejects it — without that
assertion, a regression would pass the happy path while the channel was dead.

### What has actually been run

Verified end to end on a real host over `streamable-http` (mcp 2.1.1, Python 3.14): the
eight checks pass against the live server, `tools/list` returns exactly the enabled tier,
a real `system_info` call returns live data, and a marker file reads back from an intended
path. The sandbox was confirmed by attempting the escapes — `transfer_out` to the desktop
and `write_file` to `C:\Windows` are both refused **with the reason text**, while the same
`transfer_out` into the sandbox root succeeds.

That last detail is a fix, not a detail: a refusal used to reach the client as
`Error executing tool write_file` with the policy text scrubbed, which reads as a broken
server rather than a working sandbox.

## Deploying over the internet

Use a mesh VPN (Tailscale, Headscale, Netbird) so no inbound ports are opened on the
target's router. The tailnet encrypts the transport; a relayed connection is slower but
equivalent. See `skills/rig-remote-ops/SKILL.md` for the full sequence.

## Provenance

Built behind the inkjet-rig work on `DESKTOP-AE2K3NN`, to replace the AweSun MCP that was
the only usable channel to that machine. What it stands on, and what each debt actually is:

- **`dddabtc/winremote-mcp`** (MIT) — the reference this project answers. We use no code
  from it; it is the 40-tool FastMCP server we were using and set out to replace, and the
  comparison table above is drawn against it. It in turn credits
  [`CursorTouch/Windows-MCP`](https://github.com/CursorTouch/Windows-MCP). **The one piece
  still on loan is a name:** the verifier's `WINREMOTE_RIG_TOKEN` and the vendor-profile
  tools it checks (`GetSystemInfo`/`FileRead`) are that project's vocabulary, kept so the
  verifier can still test a server you have not replaced yet. `RIG_TOKEN` and the
  `rig-gateway` profile are ours.
- **The `mcp` SDK** (MIT) — the transport and protocol this server implements. Read
  dependency, not derived code.
- **[`CursorTouch/Windows-MCP`](https://github.com/CursorTouch/Windows-MCP)** — transitive,
  credited here only because the chain would be dishonest to truncate at one link. We
  depend on it in no form.
- **`tailscale/tailscale`** (BSD-3-Clause) — carries the transport in deployment. Not a
  code dependency; the `tailscale` command in `SKILL.md` is the external CLI.

The skill in `skills/rig-remote-ops/` was reworked from the operator notes and the
`verify_endpoint.py` verifier of a first attempt, kept briefly at
`ClimbHillTmr/remote-win-mcp` and since archived. That repository holds nothing this one
does not.

## License

MIT