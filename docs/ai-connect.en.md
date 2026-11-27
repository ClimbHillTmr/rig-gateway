# Ask an AI to check a rig-gateway connection

[English home](../README.en.md) · [简体中文](ai-connect.md) · [Operator guide](operations.en.md)

For a running gateway, copy the prompt below into an AI that can call MCP tools or run Python locally. If the host or client still needs setup, use the [first-time setup prompt](ai-setup.en.md).

## First connection check

```text
Verify rig-gateway and report in English. Limit this check to tool discovery and read-only status queries.

Use the configured MCP connection first. Get the server's complete tools/list and call system_info and host_status. Match the tool names against the expected tier in skills/rig-remote-ops/SKILL.md. The default expectation is Tier 1. If the client exposes only a partial list, report the tier as unverified.

If there is no configured MCP connection but the target is a known direct private HTTP gateway, run this from the client computer's repository root:
python skills/rig-remote-ops/scripts/verify_endpoint.py --host <host-address> --port <deployed-port> --auth none --tier <expected-tier> --expect-hostname <known-hostname>
Replace the placeholders. If the hostname is unknown, omit the entire --expect-hostname option and report identity as unconfirmed. For HTTPS, mTLS, or proxy authentication, use the configured client and keep credentials there. Ask me for the target address if it is missing.

Report connection status, observed hostname and identity check, tool count and whether the expected tier matched, and the sandbox path. Preserve an unset sandbox value. On a mismatch, report the first failed step, expected and observed values, and the next check. Keep the original expectation. Deployment, restarts, file changes, remote commands, and desktop input require separate authorization.
```
