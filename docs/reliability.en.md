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

- **Configuration drift.** `--codex-entry` reads the effective Codex entry and checks its enabled state, transport, host, port, and path. A port mismatch reports the two ports and exits before network access. Diagnostics omit credentials. Omit this option to verify the recorded deployment independently. After confirming identity, tier, and the active sandbox, correct the client URL, preserve authentication and tool filters, and repeat the full check.
- **Transient loss.** With `--connect-attempts 3`, the initial TCP connection gets up to three attempts with delays of one and two seconds. Later MCP requests are never replayed by this option. The default is one attempt.
- **Acceptance.** Record three observations: the saved configuration, the response from the endpoint, and discovery or calls in the current client session. Reconnect the client, list the complete inventory, and call `system_info` and `host_status`. Check the hostname, tool names, and sandbox. The verifier can be called at client startup and exits nonzero on failure. It installs no background monitor.

## Proposed next steps

| Failure or need | Component and behavior | Acceptance criterion |
|---|---|---|
| Deployment port changes while the client keeps an old URL | Have the deployer emit a private record with the URL, instance ID, hostname, tier, sandbox, and build. Compare against that trusted record on the client. Enable automatic writes only for authorized entries. Verify the instance, update only the URL, and detect concurrent edits. | Distinguish two instances on the same host. Reject the wrong hostname, tier, or sandbox. Preserve headers, credential references, and tool filters. |
| An HTTP session expires or the network returns | The client reinitializes, negotiates the version, sends the initialized notification, and discovers tools again. Route 401/403 through the existing authentication flow. | An expired session returning 404 leads to a fresh read-only acceptance check. Retry budgets bound the delay. |
| A reply is lost after a write, move, command, or keystroke | Record the outcome as unknown. Inspect the observed state before further action. Operations requiring reliable retries need an operation ID, deduplication, and a retained result. | A completed operation with a lost reply is never automatically executed twice. |
| The process is alive but initialization repeatedly times out | Have a host-local supervisor record process state and MCP probe results separately. An authorized restart policy checks repeated local failure and in-flight jobs, then restarts only the intended instance with a bounded restart budget. | A client outage cannot trigger a host restart. Probe history, exit cause, logs, and recovery outcome are available after a local failure. |
| Clients need to identify the running build and available functions | Preserve the 15 existing tool contracts. Expose build, instance ID, start time, and tier in initialization metadata or a read-only MCP resource. Report interactive desktop state, available dependencies, and file policy separately. | Clients can distinguish a registered screenshot tool from an available interactive desktop. Existing exact-inventory checks continue to work. |
| Multiple operators, binary transfers, and audit history | Isolate role-specific instances and network ports. Give one operator control of desktop input at a time. Any future cross-machine binary transfer needs direction, limits, hash checks, and overwrite rules. Record operation ID, elapsed time, outcome, and necessary identity information. | Read-only users cannot reach operator ports. Concurrent clients cannot interleave desktop input. Timeout outcomes can be traced without logging file contents or credentials. |

Prioritize the deployment record and client checks, then session recovery with failure-injection tests, then host supervision and cross-machine transfers. MCP negotiates optional tools, resources, and prompts. Add a capability for a concrete client need. Keeping the installation prompt on GitHub makes it accessible before the gateway starts. [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) · [Streamable HTTP and session management](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
