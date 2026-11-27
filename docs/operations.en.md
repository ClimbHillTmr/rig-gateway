# rig-gateway operator guide

[English home](../README.en.md) · [简体中文](operations.md) · [AI acceptance prompt](ai-connect.en.md)

The **host** runs the Windows gateway. The **client computer** runs the MCP client. When handing over a deployment, record the Windows hostname, bind IP, TCP port, expected tier, and approved write directory. The hostname identifies the machine. The IP and port identify the endpoint. Use those recorded settings when connecting to an existing instance.

## Remote access

1. **Choose the network.** Use loopback on the host or the host’s private address on a trusted LAN or VPN. For Tailscale, sign in on the host and each client computer. Use your own account and tailnet for your devices, invite teammates through **Users**, or share the individual host with an external collaborator through **Machines → select the host → Share**. Restrict access to the host’s gateway TCP port through network policy. [Inviting vs. sharing](https://tailscale.com/docs/reference/inviting-vs-sharing) · [Sharing steps and required roles](https://tailscale.com/docs/features/sharing)
2. **Confirm the listener on the host.** Reuse an existing instance if it already listens on the intended private address and port. If you just ran the loopback quick start, stop that instance with Ctrl+C in its window. Then run the following from the installed repository root. For a LAN deployment, assign the host’s actual private IPv4 address on the first line.

   ```powershell
   $gatewayIP = tailscale ip -4
   $gatewayPort = 8099
   .\.venv\Scripts\rig-gateway.exe --transport streamable-http --host $gatewayIP --port $gatewayPort
   ```

3. **Configure the client.** Add a Streamable HTTP server at `http://<host-private-ip>:<deployed-port>/mcp`. Each authorized computer can reuse this URL. If the deployment uses a custom port, use it in the URL, network policy, and verifier.
4. **Verify from the client computer.** Run the following from its copy of the repository. The verifier uses the Python standard library. Supply the full hostname confirmed independently on the host. This example checks a direct HTTP service with no HTTP authentication and an expected tier of 1.

   ```powershell
   $gatewayIP = Read-Host 'Gateway IP'
   $gatewayPort = Read-Host 'Gateway port'
   $expectedName = Read-Host 'Expected Windows hostname'
   python .\skills\rig-remote-ops\scripts\verify_endpoint.py --host $gatewayIP --port $gatewayPort --auth none --tier 1 --expect-hostname $expectedName
   ```

A successful check matches the complete `tools/list` inventory, returns the hostname and sandbox path from `system_info`, confirms the hostname at `identity`, and exits with code 0. For a known Tier 2 or 3 deployment, use the corresponding `--tier`. If only the address is known, omit `--expect-hostname` and record that identity still needs confirmation. Use the configured client for HTTPS, mTLS, or an authenticated proxy. The repository verifier uses plain HTTP.

## A host without Git

1. On the client computer, obtain the full source archive for the intended revision. Record the revision and the archive hash from `Get-FileHash -Algorithm SHA256`. After transferring the archive, check that hash on the host and extract into a separate, owner-approved directory. The source root contains `pyproject.toml`, `README.md`, and `rig_gateway\` together. On industrial equipment, use a subdirectory of the designated workspace. When using AweSun, close the file-transfer session before opening the desktop session.
2. From that source root, follow the [first connection](../README.en.md#first-connection) steps to create a host-local virtual environment, install, and verify. Then bind to the private address as described above. Stop a foreground instance with Ctrl+C in its own window. For an upgrade, keep the previous directory, launch the new version, and verify the same endpoint and tier again. To roll back, launch from the previous directory.
3. For a deployment bundle with pinned hashes, compare its files against the script’s manifest. From a source root containing `deploy\`, the command below performs verification only. The manifest covers three Python files and `pyproject.toml`. The manifest distinguishes LF and CRLF line endings. A GitHub source archive and a deployment bundle can have different byte hashes. On a mismatch, check the publisher’s original bytes and revision and obtain the matching files. [Deployment script](../deploy/Deploy-OnRig.ps1)

   ```powershell
   .\deploy\Deploy-OnRig.ps1 -Root $PWD.Path -VerifyOnly
   ```

To launch a verified bundle with the deployment script, run `.\deploy\Deploy-OnRig.ps1` from the same source root with `-Root $PWD.Path`, the intended `-BindIp`, and the deployed `-Port`. Omit `-VerifyOnly`. The script rechecks the files, creates a `sandbox` subdirectory, and starts a foreground read-only instance by default. Use one launcher per listener.

## Permissions

| Expected tier | Startup setting | What to verify |
|---|---|---|
| 1 · 5 tools | Default | Host and system status, process list, directory and file reads. Reads use the service account’s permissions. |
| 2 · 12 tools | `--enable-tier2` | Adds file writes, directory operations, copies on the host, and screenshots. To enable file-tool writes, set `RIG_SANDBOX_ROOT` in the server environment to the approved absolute directory. |
| 3 · 15 tools | `--enable-tier3` | Adds `run_command`, `type_text`, and `press_keys`. Calling them also requires `RIG_ALLOW_TIER3=1` on the server. Shell commands inherit the service account’s operating system permissions. |

- **Files.** Check `policy.sandbox_root` with `host_status`. Supply full paths to file tools. Replacing an existing file with `write_file` requires the caller’s `overwrite=True` and the server’s `RIG_ALLOW_OVERWRITE=1`. Directory deletion requires explicit `recursive=True`. Both paths for `transfer_in` and `transfer_out` are on the host. Use a separate file-transfer channel for binary uploads or downloads between machines.
- **Desktop.** Install desktop dependencies from the host repository root with `.\.venv\Scripts\python.exe -m pip install -e ".[all]"`. Screenshots capture the active display and keystrokes reach the foreground window. Use a signed-in, unlocked interactive session and designate one person to send input.
- **Multiple users.** Everyone connecting to one instance sees its configured tools. To separate access, run read-only and operator instances on different ports and allow the appropriate users to reach each port. Industrial axis motion, servo parameter changes, and printhead firing require separate operator authorization.

## Troubleshooting

| First failing step | Where to look |
|---|---|
| Host unreachable | On the client computer, check the private network, target address, and sharing state. For Tailscale, test the route separately with `tailscale ping <host-ip>`. |
| TCP connection fails | Check the host process, bind address, deployed port, and firewall. A loopback listener is reachable only on the host. |
| TCP connects, HTTP times out or closes | Inspect the host console and proxy logs. An undrained output pipe, console text selection, or a stalled process can cause a timeout. For a closed connection, also inspect intermediary and auth settings. |
| HTTP responds, initialization or auth fails | Check the `/mcp` path, Streamable HTTP transport, and expected authentication method. |
| Unexpected `tools/list` | Compare the running process’s flags, the port the client reached, and the expected tier. Establish a fresh MCP session. |
| Hostname mismatch, unset sandbox, or blank screenshot | Confirm identity before proceeding on a mismatch. Check the running process’s sandbox before file operations. For a blank screenshot, inspect the host’s active desktop session. |

Record the first failed step, its observed result, and any fields still unverified. For the complete tool inventory and agent procedure, see the [operating skill](../skills/rig-remote-ops/SKILL.md).
