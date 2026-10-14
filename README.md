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
- **No file is overwritten without an explicit opt-in** (`RIG_ALLOW_OVERWRITE=1`).
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
python verify_endpoint.py --host 100.64.0.1 --port 8099 \
    --expect-marker-file 'C:\approved\directory\channel-marker.txt'
```

The tests are negative on purpose. `test_starved_listener_is_rejected` reproduces a socket
that accepts and never answers, and asserts the verifier rejects it — without that
assertion, a regression would pass the happy path while the channel was dead.

## Deploying over the internet

Use a mesh VPN (Tailscale, Headscale, Netbird) so no inbound ports are opened on the
target's router. The tailnet encrypts the transport; a relayed connection is slower but
equivalent. See `skills/rig-remote-ops/SKILL.md` for the full sequence.

## License

MIT