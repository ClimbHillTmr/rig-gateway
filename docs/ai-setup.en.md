# Ask an AI to set up rig-gateway from scratch

[English home](../README.en.md) · [简体中文](ai-setup.md) · [Operator guide](operations.en.md) · [Check an existing connection](ai-connect.en.md)

Copy the entire prompt into an AI that can operate the host and client computer. You can also give it this page and ask it to run “First-time setup.” Include the target host, approved installation directory, and MCP client name if known.

## First-time setup

```text
Set up rig-gateway from scratch and report in English. The goal is to read the intended Windows host’s status through my chosen MCP client. Carry out the steps below in order, using Tier 1 only. Use the source from https://github.com/ClimbHillTmr/rig-gateway

For two Windows PCs using Tailscale, use Setup-Host.cmd on the host, then transfer the verified rig-connection.json privately and run Setup-Client.cmd on the client for Codex or Claude Code. Let the user complete sign-in and permission prompts. Read both results and report the deployed URL, tier and client verification. Use the manual steps below for a different transport/client or to diagnose a failed step. Reuse an existing higher-tier instance only with the operator’s explicit approval.

1. Identify both ends. The Windows host runs the gateway and the client computer runs the MCP client. They may be the same machine. Use existing context to identify the host, authorized access channel, approved installation directory, client computer, and client application. Ask only for missing inputs. If you can operate just one side, give me the smallest required step on the other side and continue after I return the result. When uploading through AweSun, close the file session before opening the desktop session. On industrial equipment, keep source, virtual environments, and logs in the designated workspace.

2. Prepare the host. In PowerShell run [Environment]::MachineName and save the full name for the identity check. Run python --version. Python 3.10 or later is required. If missing, use the approved Python installation method, then check the version again. Reuse a checkout of known revision if available. For a new checkout, run git clone https://github.com/ClimbHillTmr/rig-gateway.git in the approved parent directory. Without Git, obtain a source ZIP for the intended revision. For a transfer, compare the archive’s SHA-256 on both machines before extracting. Record the commit or archive hash.

3. Install on the host. In the source root containing pyproject.toml, run the following commands. Skip the first line if a suitable .venv already exists. Check each result before proceeding:
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
   .\.venv\Scripts\rig-gateway.exe --help

4. Start the gateway on the host. For a same-machine setup, set $gatewayIP = '127.0.0.1'. For a separate client, use the host’s trusted private IPv4 address. If using Tailscale, check installation and sign-in on both machines. Install it from the official distribution on devices that need it, have the device user sign in, and obtain the host address with tailscale ip -4 on the host. Use the authorized private route and access rules. The gateway has no built-in HTTP authentication. Set $gatewayPort to the deployed port. For a new installation, 8099 is the default if free. Check the listener first. Reuse a verified matching Tier 1 instance if one exists. If a different instance owns the port, leave it running and select another approved free port.
   .\.venv\Scripts\rig-gateway.exe --transport streamable-http --host $gatewayIP --port $gatewayPort
   Launch from the host source root in a separate foreground session. Keep it running and record the actual URL. First-time setup needs no autostart task, remote command tools, or hardware operations.

5. Configure my chosen application on the client computer. If it is missing, install it using its official instructions and let me complete any required sign-in. Add or reuse a Streamable HTTP MCP entry at http://<host-address>:<deployed-port>/mcp. Substitute the values from step 4. For a separate computer, use the host’s private address. Preserve other entries and credentials. If a name already points to a different host, choose a new descriptive name. For Codex CLI, run add only when creating an entry. Set $gatewayUrl to the actual URL and $entryName to the chosen name, then run:
   codex mcp add $entryName --url $gatewayUrl
   codex mcp get $entryName
   For another client, enter the same fields using its installed version’s settings or configuration format. Save and reconnect or open a new session as needed.

6. Verify from the client computer. For direct HTTP, if Python and the verifier are available there, run the independent check below from the client’s repository root. Set $gatewayIP, $gatewayPort, and $expectedName on the client computer first. Use the name obtained on the host in step 2. For HTTPS or an authenticated proxy, use the configured client.
   python skills/rig-remote-ops/scripts/verify_endpoint.py --host $gatewayIP --port $gatewayPort --auth none --tier 1 --expect-hostname $expectedName
   For an existing Codex entry with a changed port, take $expectedSandbox from the trusted deployment record (unset for a read-only instance with no sandbox configured). Run the following on the client and report its verification result.
   python skills/rig-remote-ops/scripts/repair_codex.py --codex-entry $entryName --host $gatewayIP --port $gatewayPort --expect-hostname $expectedName --tier 1 --expect-sandbox $expectedSandbox
   Finally, establish an MCP session in the application configured in step 5 and obtain its complete tools/list. Expect exactly host_status, system_info, list_processes, list_directory, and read_file. Call system_info and host_status, match the full hostname, and read policy.sandbox_root. An unset sandbox is valid for a read-only instance. Record the chosen client’s actual call results even if the independent verifier passed. Report hostname or inventory differences against the original expectation. If the client exposes only a subset, mark the inventory as unverified.

Report the host installation and revision, bind address and port, client application and entry name, tool inventory, hostname match, sandbox state, and how to stop the foreground instance you started (Ctrl+C in its window). If a step fails, report the first failing step and what you observed. If my sign-in or a tool call in a new session is still required, identify that pending action.
```
