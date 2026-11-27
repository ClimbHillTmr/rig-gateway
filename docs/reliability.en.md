# Connection recovery and MCP feature design

[English home](../README.en.md) · [简体中文](reliability.md) · [Operator guide](operations.en.md)

A Windows host can run several gateway instances. In one field incident the host was online, the client still used the default port, and the deployed instance listened on another port. Initialization, inventory, and hostname checks succeeded on the deployed port. The repair was a client entry update. Restarting the host service would have left the saved URL untouched.

## Checks available today

Run this in the repository root on the client computer. Take the address, port, full Windows hostname, and expected tier from the **deployment record**. The verifier checks one direct HTTP endpoint and calls the read-only `system_info` tool by default.

```powershell
$gatewayIP = Read-Host 'Deployed host IP'
$gatewayPort = Read-Host 'Deployed gateway port'
$expectedName = Read-Host 'Expected Windows hostname'
$tier = Read-Host 'Expected tier (1, 2, or 3)'
python skills/rig-remote-ops/scripts/verify_endpoint.py --codex-entry rig-gateway --host $gatewayIP --port $gatewayPort --expect-hostname $expectedName --tier $tier --auth none --connect-attempts 3
```

- **Configuration drift.** `--codex-entry` reads the effective Codex entry and checks its enabled state, transport, host, port, and path. A port mismatch reports the two ports and exits before network access. Diagnostics omit credentials. Omit this option to verify the recorded deployment independently. To apply a verified change, run the repair command below.
- **Transient loss.** With `--connect-attempts 3`, the initial TCP connection gets up to three attempts with delays of one and two seconds. Later MCP requests are never replayed by this option. The default is one attempt.
- **Acceptance.** Record three observations: the saved configuration, the response from the endpoint, and discovery or calls in the current client session. Reconnect the client, list the complete inventory, and call `system_info` and `host_status`. Check the hostname, tool names, and sandbox. The verifier can be called at client startup and exits nonzero on failure. It installs no background monitor.

## Repair a changed Codex port

Use Python 3.10+ and a Codex CLI with app-server configuration and named MCP discovery support. In the same PowerShell session as above, supply the sandbox from the deployment record. Enter `unset` for a Tier 1 instance deployed without a sandbox.

```powershell
$expectedSandbox = Read-Host 'Expected sandbox path or unset'
python skills/rig-remote-ops/scripts/repair_codex.py --codex-entry rig-gateway --host $gatewayIP --port $gatewayPort --expect-hostname $expectedName --tier $tier --expect-sandbox $expectedSandbox
```

The command contacts the recorded IPv4 address and port, checks the MCP server name, Windows hostname, complete tier inventory and sandbox confinement, then updates only the named user URL with a configuration-version check. An already correct URL skips the write. A fresh Codex client opens the saved registration and verifies its filtered inventory. A second read-only handshake checks identity and policy again. Existing desktop chats may need to reconnect separately.

Use this for anonymous direct HTTP. Entries with credentials, custom headers or unsupported settings need their configured client. A failed post-write check triggers a version-guarded rollback. If the write receipt is lost or a concurrent change blocks rollback, inspect the saved URL before retrying. If a configuration manager repeatedly restores an old port, check its saved registration. You can call this command in your client startup routine.

## Proposed next steps

| Failure or need | Component and behavior | Acceptance criterion |
|---|---|---|
| An HTTP session expires or the network returns | The client reinitializes, negotiates the version, sends the initialized notification, and discovers tools again. Route 401/403 through the existing authentication flow. | An expired session returning 404 leads to a fresh read-only acceptance check. Retry budgets bound the delay. |
| A reply is lost after a write, move, command, or keystroke | Record the outcome as unknown. Inspect the observed state before further action. Operations requiring reliable retries need an operation ID, deduplication, and a retained result. | A completed operation with a lost reply is never automatically executed twice. |
| The process is alive but initialization repeatedly times out | Have a host-local supervisor record process state and MCP probe results separately. An authorized restart policy checks repeated local failure and in-flight jobs, then restarts only the intended instance with a bounded restart budget. | A client outage cannot trigger a host restart. Probe history, exit cause, logs, and recovery outcome are available after a local failure. |
| Clients need to identify the running build and available functions | Preserve the 15 existing tool contracts. Expose build, instance ID, start time, and tier in initialization metadata or a read-only MCP resource. Report interactive desktop state, available dependencies, and file policy separately. | Clients can distinguish a registered screenshot tool from an available interactive desktop. Existing exact-inventory checks continue to work. |
| Multiple operators, binary transfers, and audit history | Isolate role-specific instances and network ports. Give one operator control of desktop input at a time. Any future cross-machine binary transfer needs direction, limits, hash checks, and overwrite rules. Record operation ID, elapsed time, outcome, and necessary identity information. | Read-only users cannot reach operator ports. Concurrent clients cannot interleave desktop input. Timeout outcomes can be traced without logging file contents or credentials. |

Prioritize the deployment record and client checks, then session recovery with failure-injection tests, then host supervision and cross-machine transfers. MCP negotiates optional tools, resources, and prompts. Add a capability for a concrete client need. Keeping the installation prompt on GitHub makes it accessible before the gateway starts. [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) · [Streamable HTTP and session management](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
