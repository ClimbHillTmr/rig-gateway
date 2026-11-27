---
name: rig-remote-ops
description: Connect to and verify a remote Windows rig through rig-gateway. Use for MCP endpoint acceptance, tier and sandbox inspection, authorized deployment, and diagnosing a private endpoint that accepts TCP but fails MCP requests.
---

# Remote Windows operations

Use the endpoint and expected tier supplied for this host. For a new host, see the [operator guide](../../docs/operations.en.md). For an existing MCP connection, use the [read-only acceptance prompt](../../docs/ai-connect.en.md).

## Establish the scope

Record the intended host, transport, port, expected tier, and approved task. Default to Tier 1 for first contact. Ask the operator before enabling Tier 2 or 3. If a higher-tier endpoint is already running, use only the tools authorized for the task. Physical motion, servo configuration, and printhead firing require explicit operator authorization.

When uploading a gateway through AweSun, keep the deployment within the owner-approved directory. Close the file session before opening the desktop session. Verify the package and endpoint separately. Keep the recovery channel available until the capabilities required by the operator have been verified.

## Tool inventory

Compare the **complete set of names**. Each row adds tools to the preceding tier.

| Tier | Total | Names added | Gateway CLI |
|---|---:|---|---|
| 1 | 5 | `host_status`, `system_info`, `list_processes`, `list_directory`, `read_file` | Default |
| 2 | 12 | `capture_screen`, `write_file`, `make_directory`, `move_path`, `delete_path`, `transfer_in`, `transfer_out` | `--enable-tier2` |
| 3 | 15 | `run_command`, `type_text`, `press_keys` | `--enable-tier3` |

Tier 3 calls also require `RIG_ALLOW_TIER3=1` in the server environment. Listing a tool confirms its registration. A read-only acceptance check ends after inventory, a status call, and identity verification.

## Verify a connection

1. **Route.** When diagnosing a Tailscale connection, run `tailscale ping <host>` separately. A relayed connection is sufficient. For stdio, the client starts the local process and can proceed directly to MCP initialization.
2. **TCP and HTTP.** For a network endpoint, confirm the address and socket, then obtain an HTTP response at `/mcp`. HTTP status codes establish that a responder exists. Record the authentication behavior separately.
3. **Protocol and inventory.** Initialize an MCP session and request `tools/list`. Keep the operator’s original expectation on a mismatch. If the client shows only a subset of tools, record the tier as unverified.
4. **Execution and identity.** Call `system_info`, match the full hostname to an independently known value, and inspect `host_status().policy` for the live sandbox. Report an unknown expected hostname as unconfirmed. A pre-existing marker can be read as an additional check. Compare its content with a known value when identity depends on it.

For direct HTTP, the bundled [verifier](scripts/verify_endpoint.py) checks TCP, HTTP, initialization, inventory, and a tool call. Supply the expected hostname to check identity. From the skill directory:

```powershell
$gatewayIP = Read-Host 'Gateway IP'
$gatewayPort = Read-Host 'Gateway port'
$expectedName = Read-Host 'Expected Windows hostname'
python .\scripts\verify_endpoint.py --host $gatewayIP --port $gatewayPort --auth none --tier 1 --expect-hostname $expectedName
```

Use `--auth none` for the gateway’s unauthenticated endpoint. The verifier sends no bearer token in this mode. Use the configured client for HTTPS or mTLS. The verifier also supports a bearer-authenticated HTTP service with `--auth required` and the older `--profile vendor` naming. Keep credentials out of commands, logs, and the repository.

For Codex, pass `--codex-entry NAME` to compare the effective entry with the expected direct HTTP endpoint before probing. With `--connect-attempts 3`, transient failures during the initial TCP connection are retried twice. If the entry differs, verify the recorded deployment independently. A repair request for that same instance can then update its local URL while preserving other settings. Establish a new client session and verify again. [Recovery procedure and design](../../docs/reliability.en.md)

## Use authorized tools

- Read paths use the service account’s permissions. File-tool mutations require a configured `RIG_SANDBOX_ROOT`. Use absolute paths and check the current `policy.sandbox_root` before writing.
- Replacing a file with `write_file` requires both `overwrite=True` and the server’s `RIG_ALLOW_OVERWRITE=1`. Directory deletion requires `recursive=True`. Both transfer endpoints are on the Windows host, and the destination is confined to the sandbox.
- Shell commands run with the service account’s permissions outside the file-tool sandbox. Keyboard input reaches the foreground window. Confirm the interactive session and intended window before authorized input.
- Report each observation separately: package hash, endpoint response, exact inventory, tool result, and any physical outcome explicitly confirmed by the operator.

## Diagnose the first failed step

| Observation | Next check |
|---|---|
| TCP refused or unreachable | Host route, bind address, process, actual port, firewall and tailnet access rules |
| Socket accepted, then no HTTP response | Server console and logs, undrained stdout/stderr pipes, paused console selection, stalled worker |
| Connection closed without an HTTP response | Server and proxy logs, session handling, and authentication policy. The symptom alone does not identify the cause. |
| HTTP 401/403 | Compare the configured authentication method with the endpoint policy |
| Handshake succeeds but inventory or hostname differs | Verify the process, URL, tier and intended host. Record the mismatch before any higher-tier action. |
