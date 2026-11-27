# 让 AI 从零接入 rig-gateway

[中文首页](../README.md) · [English](ai-setup.en.md) · [操作手册](operations.md) · [仅验收现有连接](ai-connect.md)

把下面整段复制给能操作目标机和控制端的 AI。也可以把本页链接发给 AI，让它执行「从零接入」。如果你知道目标机、允许的安装目录和 MCP 客户端名称，可以一起告诉它。

## 从零接入

```text
请从零完成 rig-gateway 的首次接入，并用中文报告结果。目标是在我选定的 MCP 客户端里，从指定 Windows 目标机读回主机状态。按以下顺序执行可操作的步骤，默认只开放 Tier 1。从 https://github.com/ClimbHillTmr/windows-rig-mcp 获取源码。

两台 Windows 电脑通过 Tailscale 接入 Codex 或 Claude Code 时，在目标机运行 Setup-Host.cmd，私下传递验收生成的 rig-connection.json，再在使用机运行 Setup-Client.cmd。交互登录和系统授权由使用者完成。读取两端结果并报告实际 URL、权限和客户端验收情况。其他传输、客户端或故障诊断按下列手动步骤处理。复用已有高权限实例前核对操作员授权。

1. 确认两端。目标机运行网关，控制端运行 MCP 客户端，两者可以是同一台电脑。先从现有上下文确认目标机、已授权的操作通道、允许的安装目录、控制端和客户端名称。只询问缺少的信息。若你只能操作一端，把另一端当前需要执行的最小步骤交给我，拿到结果后继续。若通过 AweSun 上传，先关闭文件会话再开桌面会话。工业设备上的源码、虚拟环境及日志都放在指定工作目录内。

2. 在目标机准备环境。在 PowerShell 运行 [Environment]::MachineName，保存完整机名供最后比对。检查 python --version，需要 Python 3.10 或更新版本；缺少时用获准的 Python 安装方式补齐，再检查版本。优先复用版本明确的仓库目录。新安装可在获准的父目录运行 git clone https://github.com/ClimbHillTmr/windows-rig-mcp.git；没有 Git 就取得同版本源码 ZIP，跨机传输时核对包的 SHA-256，再解压。记录提交号或包哈希。

3. 在目标机安装。在含 pyproject.toml 的源码根目录运行下列命令；若已有适用的 .venv，跳过第一行。每步确认成功再继续：
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
   .\.venv\Scripts\rig-gateway.exe --help

4. 在目标机启动。同机首次使用令 $gatewayIP = '127.0.0.1'。跨机用目标机的受信私网 IPv4；若选择 Tailscale，在两端检查安装和登录状态。缺少 Tailscale 的设备从官方渠道安装，由设备使用者完成登录，再在目标机用 tailscale ip -4 取地址。使用已获准的私网路由和访问规则。网关没有内置 HTTP 认证。将 $gatewayPort 设为实际部署端口；新安装可用空闲的 8099。先核对监听进程，已有匹配且经核实的 Tier 1 实例可直接复用。端口被其他实例占用时保留它，另选获准的空闲端口。
   .\.venv\Scripts\rig-gateway.exe --transport streamable-http --host $gatewayIP --port $gatewayPort
   从目标机源码根目录在独立的前台会话中启动，保持该会话运行，记录实际 URL。首次接入不需要开机自启动、命令执行或硬件操作。

5. 在控制端配置我指定的客户端。若尚未安装，先按该客户端的官方方式安装，并由我完成需要的登录。新增或复用一个 Streamable HTTP 类型的 MCP 条目，URL 为 http://<目标机地址>:<实际端口>/mcp。将占位符换成第 4 步的值，跨机时使用目标机私网地址。保留其他条目和凭据；若同名条目指向别的目标，选用新的描述性名称。以 Codex CLI 为例，仅在需要新增条目时执行 add。设置 $gatewayUrl 为实际 URL、$entryName 为选定名称，再执行：
   codex mcp add $entryName --url $gatewayUrl
   codex mcp get $entryName
   对其他客户端，按其已安装版本的设置界面或配置格式填写相同字段。保存后按需重连或开启新会话。

6. 从控制端验证。对于直连 HTTP，若控制端有 Python 和仓库脚本，从控制端仓库根目录运行下面的独立检查。先在控制端设置 $gatewayIP、$gatewayPort 和 $expectedName；机名使用第 2 步在目标机读到的值。HTTPS 或认证代理使用已配置的客户端。
   python skills/rig-remote-ops/scripts/verify_endpoint.py --host $gatewayIP --port $gatewayPort --auth none --tier 1 --expect-hostname $expectedName
   若已有 Codex 条目的端口变化，从可信部署记录取得 $expectedSandbox（只读部署未配置写入根目录时填 unset），在控制端执行下面的命令并报告验收结果。
   python skills/rig-remote-ops/scripts/repair_codex.py --codex-entry $entryName --host $gatewayIP --port $gatewayPort --expect-hostname $expectedName --tier 1 --expect-sandbox $expectedSandbox
   最后在第 5 步配置的客户端建立 MCP 会话，取得完整 tools/list。预期恰好有 host_status、system_info、list_processes、list_directory、read_file。实际调用 system_info 和 host_status，核对完整 hostname，并读取 policy.sandbox_root。只读实例的沙箱可为未配置。即使独立检查通过，也要记录所选客户端的实际调用结果。主机名或清单不符时保留原预期，报告差异；客户端只展示部分工具时标注清单待核实。

交付时分别写明目标机安装结果与版本、监听地址和端口、控制端客户端与条目名、工具清单、机名是否匹配、沙箱状态，以及如何停止本次启动的前台进程（在对应窗口按 Ctrl+C）。若某一步失败，报告失败位置和实测结果；若仍需我登录或在新会话调用工具，注明待完成的具体动作。
```
