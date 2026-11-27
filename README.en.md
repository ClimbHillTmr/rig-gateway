# rig-gateway

[简体中文](README.md) · **English**

Run a self-hosted MCP server on a Windows machine so an AI client can inspect its system, processes, and files over a private network. The default configuration exposes five read-only tools. Enable a higher tier on the Windows host when you need screenshots, file changes, or shell commands.

**Already connected an MCP client?** Send your AI the prompt below. A [longer acceptance prompt is available in Chinese](docs/ai-connect.md).

> Check the configured rig-gateway connection. List its tools, call `system_info` and `host_status`, and report the observed hostname, tool count, and sandbox path. Use read-only checks throughout.

## First connection

Start on a Windows machine with **Python 3.10 or later**. Open both PowerShell windows in the repository root.

**1. Start the server on the Windows host.** The loopback address keeps this first session local. Leave the window open.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\rig-gateway.exe --transport streamable-http --host 127.0.0.1 --port 8099
```

**2. Verify the connection on the same machine.** In a second window, run the verifier. It negotiates an MCP session, checks the tool names, and calls `system_info` to verify the hostname.

```powershell
.\.venv\Scripts\python.exe .\skills\rig-remote-ops\scripts\verify_endpoint.py --host 127.0.0.1 --port 8099 --auth none --tier 1 --expect-hostname ([Environment]::MachineName)
```

**A successful run** ends when `tools/list` reports the five expected tools, `identity` confirms the full hostname, and the verifier exits with code 0. A sandbox value of `(unset)` is expected on a first read-only run.

## Connect an MCP client

| Client location | Configuration |
|---|---|
| Same Windows host, over HTTP | Select **Streamable HTTP** and enter `http://127.0.0.1:8099/mcp`. |
| Same Windows host, over stdio | Set the executable to the absolute path of `.venv\Scripts\rig-gateway.exe` and pass `--transport` and `stdio` as arguments. The client starts the process. |
| Another machine on your private network | Stop the test server with Ctrl+C. Run the start command again with the host’s private IPv4 address as `--host`. Set the client URL to `http://<host-private-ipv4>:8099/mcp`. |

The gateway has no built-in HTTP authentication. For remote access, restrict which devices can connect through network access rules or put an authenticated proxy in front of the server. When running the verifier on the client machine, pass the **known Windows host name** to `--expect-hostname`. PowerShell evaluates `([Environment]::MachineName)` on the machine running the command.

## Connect through Tailscale

**Do I need to install it?** You can use rig-gateway directly over stdio or `127.0.0.1` on the same computer, or over a trusted LAN or VPN that already connects both machines. For a direct Tailscale connection, install Tailscale and sign in on **the Windows gateway host** and **each computer running an MCP client**. Devices already online in Tailscale are ready to use. Only the host needs to run the gateway. [Download Tailscale for Windows](https://tailscale.com/download/windows)

| Who needs access? | How to connect |
|---|---|
| My second computer | Sign in to Tailscale with your own account on the new computer and select the host’s private network (tailnet). Enter the same gateway URL in the new computer’s MCP client. |
| Teammates with their own accounts | An admin invites members from **Users** in the Tailscale admin console. Each member accepts with their own account and joins the team tailnet on their client computer. Use access rules to limit which members can reach the host on the gateway’s TCP port. |
| An external collaborator who needs only this host | An admin sends a single-use invitation from **Machines → select the host → Share**. The recipient accepts the share in their own tailnet. Both tailnets’ access rules must allow the connection. |

**Which URL do I use?** Run `tailscale ip -4` on the host to get its Tailscale IPv4 address. On first startup, pass that address to the gateway’s `--host` flag. If the gateway is already listening there, reuse it. On each client, select **Streamable HTTP** and enter `http://<host-tailscale-ip>:<actual-port>/mcp`. The default port is `8099`. Use the deployed `--port` value if it differs. Run the verifier above from the client with the host’s address, port, and expected hostname.

**How do permissions work for multiple users?** Tailscale rules control which users or devices can reach a port. Each gateway instance exposes the tool tier selected at startup to everyone who can connect to it. To give colleagues read-only access, run a Tier 1 instance on a separate port and grant access to the higher-tier port only to operators. [Inviting users vs. sharing a device](https://tailscale.com/docs/reference/inviting-vs-sharing) · [Device sharing instructions](https://tailscale.com/docs/features/sharing)

## Tools and permissions

Each tier includes the tiers below it. After changing the startup flags, restart the server, reconnect the client, and check the expected inventory with `--tier 1`, `--tier 2`, or `--tier 3` on the verifier.

| Tier | Startup flag | Total tools | Capabilities added |
|---|---|---:|---|
| 1 · Diagnostics | Default | 5 | Host status, system info, process list, directory listing, and file reads |
| 2 · Files and screenshots | `--enable-tier2` | 12 | Capture the active display, write text, create directories, move or delete paths, and copy files on the host |
| 3 · Commands and input | `--enable-tier3` | 15 | Run shell commands, type text, and send key combinations. Calling these three tools also requires `RIG_ALLOW_TIER3=1` on the server. |

- **Files.** In the PowerShell session that starts the server, set `$env:RIG_SANDBOX_ROOT` to the absolute directory approved for writes. Reads use the service account’s permissions. Replacing a file with `write_file` requires both the caller’s `overwrite=True` and the server’s `RIG_ALLOW_OVERWRITE=1`. Deleting a directory requires `recursive=True`.
- **Copies.** Both paths passed to `transfer_in` and `transfer_out` are on the Windows host. The destination must be inside the sandbox. Use a separate file-transfer channel for binary uploads and downloads between machines.
- **Desktop.** Install the desktop dependencies from the repository root with `.\.venv\Scripts\python.exe -m pip install -e ".[all]"`. The target user needs a signed-in, unlocked desktop. Screenshots capture the active display. Keyboard tools support typing and shortcuts.
- **Commands.** `run_command` runs with the service account’s permissions, outside the file tools’ sandbox. Industrial axis motion, servo parameter changes, and printhead firing require separate operator authorization.

## Troubleshooting

| Symptom | First check |
|---|---|
| Verification succeeds on the host, but the remote client cannot connect | Compare the bind address with the client URL, then check the private network route, port, and access rules. |
| TCP connects, but the MCP handshake times out | Inspect the server console. Check for an undrained output pipe or a console paused by a text selection. |
| The tool inventory differs from the expected tier | Compare the running process’s startup flags with the verifier’s `--tier`. Reconnect the client and request `tools/list` again. |

For a host without Git, upload the deployment files and use the deployment script’s `-VerifyOnly` option to check their SHA-256 hashes. When bootstrapping through AweSun, close the file-transfer session before opening the desktop session. [Deployment script](deploy/Deploy-OnRig.ps1) · [Remote operations guide](skills/rig-remote-ops/SKILL.md)

## Development and license

Run the tests from the repository root.

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
```

The server uses the Python MCP SDK. Its tool design draws on `dddabtc/winremote-mcp`, which credits `CursorTouch/Windows-MCP`. The operating skill and verifier grew out of `ClimbHillTmr/remote-win-mcp`. The verifier retains `--profile vendor` for legacy tool names. [MIT license](LICENSE)
