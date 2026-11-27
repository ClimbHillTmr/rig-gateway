# rig-gateway

**简体中文** · [English](README.en.md)

让 AI 客户端以只读方式查看 Windows 主机的状态、进程和文件。网关运行在目标 Windows 主机上。同机客户端可以通过 stdio 启动网关，其他电脑可以通过私网访问它的 Streamable HTTP 服务。

| 你现在的情况 | 从这里开始 |
|---|---|
| MCP 客户端已经配置了目标机 | [让 AI 验收现有连接](docs/ai-connect.md) |
| 目标机还没有运行网关 | [安装并验证首次连接](#首次连接) |
| 想从第二台电脑或同事的账号连接 | [通过 Tailscale 连接](#通过-tailscale-连接) |
| 需要部署、重启或诊断故障 | [操作手册](docs/operations.md) |

如果客户端已经连好，可以直接发给 AI：

> 请列出 rig-gateway 的完整工具清单，调用 `system_info` 和 `host_status`，报告主机名、工具数和沙箱路径。只执行只读检查。

## 首次连接

目标 Windows 主机需要 **Python 3.10 或更新版本**。先用 Git 克隆本仓库，或从 GitHub 的 **Code → Download ZIP** 下载并解压。打开含有 `pyproject.toml` 的目录，以下两个 PowerShell 窗口都从这里开始。

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

| 客户端在哪里？ | 应填写什么？ |
|---|---|
| 目标机上，使用 stdio | 程序填 `.venv\Scripts\rig-gateway.exe` 的绝对路径，参数填 `--transport` 和 `stdio`。客户端自行启动进程。 |
| 目标机上，使用 HTTP | 选择 **Streamable HTTP**。若使用上面的启动命令，URL 填 `http://127.0.0.1:8099/mcp`。 |
| 另一台电脑上 | 选择 **Streamable HTTP**，URL 填 `http://<目标机私网IP>:<部署端口>/mcp`。服务须监听该网卡的地址，端口以目标机实际配置为准。 |

## 通过 Tailscale 连接

同机使用，或两台电脑已能通过受信局域网或 VPN 互通时，Tailscale 是可选的。选择 Tailscale 直连时，在目标机和每台控制电脑上安装并登录。只有目标机需要运行网关。[下载 Windows 版](https://tailscale.com/download/windows)

- **自己的第二台电脑**：用自己的账号登录，选择同一个 Tailscale 私网。
- **团队成员**：管理员在 **Users** 邀请同事自己的账号，并放行目标机的网关端口。
- **外部协作者**：在 **Machines → Share** 单独共享目标机。双方私网的访问规则均须允许这次连接。

在目标机运行 `tailscale ip -4` 可取得绑定地址，获准访问的客户端共用同一 URL。[配置目标端并从第二台电脑验收](docs/operations.md#远程接入)

## 工具与权限

默认实例提供 **5 个只读工具**。`--enable-tier2` 开放文件操作与截图，共 **12 个工具**。`--enable-tier3` 共 **15 个工具**，调用命令和键盘工具还需在服务端设置 `RIG_ALLOW_TIER3=1`。网关没有内置 HTTP 认证，对外提供私网服务前应限定访问范围。[文件、桌面和命令的权限说明](docs/operations.md#权限设置)

## 连接故障

如果本机通过、远程失败，先核对绑定地址和实际端口，再按验证器第一个失败的步骤定位原因。[按现象排障](docs/operations.md#故障排查)

## 开发与许可

在仓库根目录运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
```

项目使用 Python MCP SDK。工具设计参考 `dddabtc/winremote-mcp` 及其致谢的 `CursorTouch/Windows-MCP`。操作技能与验证器延续自 `ClimbHillTmr/remote-win-mcp`，旧工具名仍可通过 `--profile vendor` 验证。[MIT 许可证](LICENSE)
