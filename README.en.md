# rig-gateway

[简体中文](README.md) · **English**

Give an AI client read-only access to a Windows host’s status, processes, and files. The gateway runs on the Windows host. A client on that machine can launch it over stdio, or a client elsewhere can connect to its Streamable HTTP endpoint over a private network.

| What are you starting with? | Start here |
|---|---|
| First use, with the host or client still to set up | [Ask an AI to install, configure, and verify](docs/ai-setup.en.md) · [Manual setup](#first-connection) |
| An MCP client already configured for this host | [Give the AI a read-only connection check](docs/ai-connect.en.md) |
| Another computer or a colleague’s account | [Connect through Tailscale](#connect-through-tailscale) |
| A deployment to maintain or a connection that fails | [Operator guide](docs/operations.en.md) |

If your client is already connected, send it this prompt:

> List the configured rig-gateway tools. Call `system_info` and `host_status`, then report the observed hostname, tool count, and sandbox path. Use read-only checks throughout.

## First connection

Start on a Windows machine with **Python 3.10 or later**. Clone this repository or select **Code → Download ZIP** on GitHub and extract the archive. Open both PowerShell windows in the directory containing `pyproject.toml`.

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

| Where is the client? | What to enter |
|---|---|
| On the host, over stdio | The absolute path to `.venv\Scripts\rig-gateway.exe`, with arguments `--transport` and `stdio`. The client starts its own process. |
| On the host, over HTTP | Select **Streamable HTTP** and enter `http://127.0.0.1:8099/mcp` for the instance started above. |
| On another computer | Select **Streamable HTTP** and enter `http://<host-private-ip>:<deployed-port>/mcp`. The service must listen on that interface. Use the actual port from the host. |

## Connect through Tailscale

Tailscale is optional for local use and for computers that can already reach each other on a trusted LAN or VPN. To connect directly over Tailscale, install it on the gateway host and each client computer and sign in. Only the host runs the gateway. [Windows download](https://tailscale.com/download/windows)

- **Your second computer:** use your own account and select the same tailnet.
- **A teammate:** invite their own account to your tailnet through **Users** and allow access to the gateway port.
- **An external collaborator:** share the individual host through **Machines → Share**. Both tailnets must allow the connection.

On the host, `tailscale ip -4` gives the address to bind. All authorized clients can reuse that endpoint. [Configure the host and verify from a second computer](docs/operations.en.md#remote-access)

## Tools and permissions

The default instance advertises **5 read-only tools**. `--enable-tier2` advertises **12** including file changes and screenshots. `--enable-tier3` advertises **15**. Calling the shell and keyboard tools also requires `RIG_ALLOW_TIER3=1` on the server. The gateway has no built-in HTTP authentication. Limit network access before exposing an endpoint. [File, desktop, and command permissions](docs/operations.en.md#permissions)

## Troubleshooting

If the local check passes but the remote client fails, compare the bind address and deployed port first. Use the first failed verifier step to narrow down the cause. [Troubleshooting by symptom](docs/operations.en.md#troubleshooting)

## Development and license

Run the tests from the repository root.

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
```

The server uses the Python MCP SDK. Its tool design draws on `dddabtc/winremote-mcp`, which credits `CursorTouch/Windows-MCP`. The operating skill and verifier grew out of `ClimbHillTmr/remote-win-mcp`. The verifier retains `--profile vendor` for legacy tool names. [MIT license](LICENSE)
