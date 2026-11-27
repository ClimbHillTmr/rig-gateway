# rig-gateway

**简体中文** · [English](README.en.md)

在 Windows 设备上运行一个自托管的 MCP 服务，让 AI 客户端通过私有网络检查设备状态、进程和文件。默认开放 5 个只读工具。需要截图、写文件或发送命令时，可以在目标机上选择更高的权限级别。

**已经配置好 MCP？** 把下面这句话发给客户端里的 AI，或使用[完整验收提示词](docs/ai-connect.md)。

> 请检查已配置的 rig-gateway 连接。列出工具，调用 `system_info` 和 `host_status`，报告实际主机名、工具数量和沙箱路径。只做只读检查。

## 首次连接

准备一台安装了 **Python 3.10 或更新版本**的 Windows 机器。以下命令使用 PowerShell，两个窗口都从仓库根目录开始。

**1. 在目标机启动服务。** 首次使用回环地址，只允许本机连接。保持这个窗口打开。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\rig-gateway.exe --transport streamable-http --host 127.0.0.1 --port 8099
```

**2. 在同一台机器验证连接。** 打开第二个窗口。验证器会完成 MCP 握手，比对工具名称，再调用 `system_info` 核对主机名。

```powershell
.\.venv\Scripts\python.exe .\skills\rig-remote-ops\scripts\verify_endpoint.py --host 127.0.0.1 --port 8099 --auth none --tier 1 --expect-hostname ([Environment]::MachineName)
```

**成功标志**是 `tools/list` 恰好列出 5 个预期工具、`identity` 确认完整主机名，且脚本退出码为 0。首次只读运行时，沙箱显示 `(unset)` 属于正常结果。

## 接入 MCP 客户端

| 客户端位置 | 配置方式 |
|---|---|
| 同一台 Windows 主机，使用 HTTP | 选择 **Streamable HTTP**，URL 填 `http://127.0.0.1:8099/mcp`。 |
| 同一台 Windows 主机，使用 stdio | 程序填 `.venv\Scripts\rig-gateway.exe` 的绝对路径，参数填 `--transport` 和 `stdio`。客户端负责启动进程。 |
| 私有网络中的另一台机器 | 在目标机按 Ctrl+C 停止试用实例。用上面的启动命令重新运行，将 `--host` 改成目标机的私网 IPv4。客户端 URL 填 `http://<目标机私网IPv4>:8099/mcp`。 |

网关本身没有 HTTP 身份认证。远程连接时，请用私网访问控制规则限制哪些设备可以连接，或在网关前配置认证代理。从控制端运行验证器时，将 `--expect-hostname` 设为已知的**目标机名**。`([Environment]::MachineName)` 取的是运行命令的这台机器的名称。

## 工具与权限

权限逐级累加。调整启动参数后，重启服务并重新连接。用验证器的 `--tier 1`、`--tier 2` 或 `--tier 3` 核对预期清单。

| 级别 | 启动参数 | 工具总数 | 本级新增能力 |
|---|---|---:|---|
| 1 · 诊断 | 默认 | 5 | 主机状态、系统信息、进程、目录、文件读取 |
| 2 · 文件与截图 | `--enable-tier2` | 12 | 截取活动显示器画面、写文本、创建目录、移动、删除、在目标机内复制文件 |
| 3 · 命令与输入 | `--enable-tier3` | 15 | 运行 shell 命令、输入文本、发送组合键；调用这三项还需在服务端设置 `RIG_ALLOW_TIER3=1` |

- **文件。** 在启动服务的 PowerShell 中，将 `$env:RIG_SANDBOX_ROOT` 设为获准写入的绝对目录。读取范围取决于服务账户的权限。`write_file` 覆盖已有文件还需要调用方传入 `overwrite=True`，并在服务端设置 `RIG_ALLOW_OVERWRITE=1`。删除目录需要显式传入 `recursive=True`。
- **复制。** `transfer_in` 和 `transfer_out` 的两个路径都位于目标机，目标路径须在沙箱内。控制端与目标机之间传输二进制文件时，使用单独的文件传输通道。
- **桌面。** 在仓库根目录运行 `.\.venv\Scripts\python.exe -m pip install -e ".[all]"`，并保持目标用户桌面已登录、已解锁。截图支持活动显示器，输入支持打字和快捷键。
- **命令。** `run_command` 继承服务账户权限，文件工具的沙箱不约束 shell。工业设备的轴运动、伺服参数变更和喷头操作须由操作员单独授权。

## 连接故障

| 现象 | 首先检查 |
|---|---|
| 目标机本地验证通过，控制端连不上 | 对照目标机的绑定地址和客户端 URL，再检查私网路由、端口及访问控制规则。 |
| TCP 能连接，MCP 握手超时 | 查看服务端控制台。检查输出是否被送入无人读取的管道，或控制台是否因拖选文本而暂停。 |
| 工具清单与预期不符 | 对照运行中服务的启动参数和验证器的 `--tier`。客户端重新连接后，再查一次 `tools/list`。 |

目标机没有 Git 时，可上传部署文件后用部署脚本的 `-VerifyOnly` 校验 SHA-256。若通过 AweSun 上传并启动，请先关闭文件通道，再切换到桌面通道。[部署脚本](deploy/Deploy-OnRig.ps1) · [远程操作与排障手册（英文）](skills/rig-remote-ops/SKILL.md)

## 开发与许可

在仓库根目录运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
```

项目使用 Python MCP SDK。工具设计参考 `dddabtc/winremote-mcp` 及其致谢的 `CursorTouch/Windows-MCP`。操作技能与验证器延续自 `ClimbHillTmr/remote-win-mcp`，旧工具名仍可通过 `--profile vendor` 验证。[MIT 许可证](LICENSE)
