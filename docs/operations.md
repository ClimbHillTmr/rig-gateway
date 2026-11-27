# Windows Rig MCP 操作手册

[简体中文首页](../README.md) · [English](operations.en.md) · [AI 验收提示词](ai-connect.md)

**目标机**运行网关，**控制端**运行 MCP 客户端。在交接一次部署时，记录目标机的 Windows 主机名、监听 IP、TCP 端口、预期权限级别和已批准的写入目录。主机名用来核对身份，IP 和端口用来连接。连接已有服务时先使用这份记录。

## 真机操作面板

把 [operator-panel 文件夹](../deploy/operator-panel)中的三个文件放在目标机同一目录，双击 `Open-Panel.cmd`。新的一键部署使用当前用户的 `rig-gateway-user` 登录任务。已有现场部署时，面板读取任务计划程序根目录下的 `rig-gateway` 开机任务，从现有 `Run-Task.ps1` 启动参数取得监听地址、端口和权限级别。只有前台进程的部署会显示网关控制不可用。

- **启动连接**会启动已有网关任务。面板显示实际配置的 URL、任务状态和端口监听状态。启动后点“刷新状态”，再从控制端验收 MCP。
- **启动 Tailscale** 会按需启动已安装的 Windows 服务并请求连接。需要登录时，在真机完成登录。同机回环、可达的受信局域网或其他 VPN 都可以不用 Tailscale。若网关只监听 Tailscale IP，当前 URL 就需要这条网络。
- **启用 / 关闭开机启动**控制已有的开机触发器。另有登录任务时，面板单独显示其状态；即使关闭开机触发，启用的登录任务仍可在用户登录时启动网关。修改开机触发器需要任务管理权限。打开面板只读取状态。

## 远程接入

1. **准备网络。** 同机用回环地址，受信局域网或已有 VPN 用目标机的私网地址。使用 Tailscale 时，在目标机和每台控制端分别登录。自己的设备用同一账号和私网；团队成员接受管理员在 **Users** 发出的邀请；外部用户接受 **Machines → 目标机 → Share** 发出的设备共享。用访问规则限定谁能访问该主机上的网关 TCP 端口。[邀请与共享的区别](https://tailscale.com/docs/reference/inviting-vs-sharing) · [共享步骤与所需角色](https://tailscale.com/docs/features/sharing)
2. **确认目标机监听地址。** 已运行的实例如果已绑定所需私网地址和端口，直接复用。若是刚完成首页的回环试用，在该试用窗口按 Ctrl+C，再运行下例。命令从已安装网关的仓库根目录执行。局域网部署可将第一行替换为实际私网 IPv4 的赋值。

   ```powershell
   $gatewayIP = tailscale ip -4
   $gatewayPort = 8099
   .\.venv\Scripts\rig-gateway.exe --transport streamable-http --host $gatewayIP --port $gatewayPort
   ```

3. **配置控制端。** 添加 Streamable HTTP 服务器，URL 填 `http://<目标机私网IP>:<实际端口>/mcp`。新控制电脑复用同一 URL。部署选择了其他端口时，客户端 URL、网络访问规则、验证命令都要使用实际值。
4. **从控制端验收。** 在控制端仓库根目录运行下例。脚本只需 Python 标准库。填写从目标机独立确认的完整机名。以下命令用于直连、无 HTTP 认证、预期 Tier 1 的服务。

   ```powershell
   $gatewayIP = Read-Host 'Gateway IP'
   $gatewayPort = Read-Host 'Gateway port'
   $expectedName = Read-Host 'Expected Windows hostname'
   python .\skills\rig-remote-ops\scripts\verify_endpoint.py --host $gatewayIP --port $gatewayPort --auth none --tier 1 --expect-hostname $expectedName
   ```

验证通过时，`tools/list` 与预期清单完全匹配，`system_info` 返回主机名和沙箱路径，`identity` 确认机名，退出码为 0。若已知部署为 Tier 2 或 3，使用相应的 `--tier`。仅知道 IP 时可以省略 `--expect-hostname`，记录「连接成功，身份待确认」。HTTPS、mTLS 或认证代理按已有客户端配置验证；仓库脚本直接使用 HTTP。

## 没有 Git 的目标机

1. 在控制端从选定的仓库版本取得完整源码包，记录版本和 `Get-FileHash -Algorithm SHA256` 得到的包哈希。传到目标机后核对相同哈希，再解压到机主批准的独立目录。源码根应同时含有 `pyproject.toml`、`README.md` 和 `rig_gateway\`。工业设备使用指定工作目录下的子目录。通过 AweSun 上传时，传输完成后关闭文件通道，再打开桌面通道。
2. 在解压后的源码根目录按[首次连接](../README.md#首次连接)创建目标机自己的虚拟环境、安装并验证。确认工作正常后，再按上节绑定私网地址。结束前台服务时，在对应窗口按 Ctrl+C。升级时保留原版本目录，从新版本启动，用相同的端点和权限设置再次验收；需要回退时切回原目录。
3. 若收到的是带固定哈希的部署包，可对照脚本的清单核对文件。下例在包含 `deploy\` 的源码根执行，仅做校验。脚本清单覆盖三个 Python 文件和 `pyproject.toml`；该清单对 LF 和 CRLF 换行敏感，从 GitHub 下载的源码包与部署包可能具有不同的字节哈希。出现不匹配时，对照发布者的原始字节及包版本重新取得匹配的文件。[部署脚本](../deploy/Deploy-OnRig.ps1)

   ```powershell
   .\deploy\Deploy-OnRig.ps1 -Root $PWD.Path -VerifyOnly
   ```

若选择部署脚本启动，在同一源码根目录向 `.\deploy\Deploy-OnRig.ps1` 传入 `-Root $PWD.Path`、`-BindIp` 和实际 `-Port`，省略 `-VerifyOnly`。脚本会重新校验文件，建立 `sandbox` 子目录并以前台只读模式启动。不要同时启动首页示例的实例和部署脚本实例占用同一端口。

## 权限设置

| 预期级别 | 如何启动 | 验收与使用边界 |
|---|---|---|
| 1 · 5 个工具 | 默认 | 查看主机、系统、进程、目录和文件。读取范围由服务账户决定。 |
| 2 · 12 个工具 | `--enable-tier2` | 新增写文件、目录操作、目标机内复制和截图。对文件工具开放写入前，在服务进程环境中设置 `RIG_SANDBOX_ROOT` 为已批准的绝对目录。 |
| 3 · 15 个工具 | `--enable-tier3` | 新增 `run_command`、`type_text`、`press_keys`。实际调用还要求服务端 `RIG_ALLOW_TIER3=1`。Shell 继承服务账户的系统权限。 |

- **文件。** 用 `host_status` 核对 `policy.sandbox_root`。调用文件工具时写完整路径。`write_file` 覆盖现有文件需调用方传 `overwrite=True` 且服务端设置 `RIG_ALLOW_OVERWRITE=1`。删除目录需显式传 `recursive=True`。`transfer_in` 和 `transfer_out` 都在目标机上复制，跨机器上传或下载二进制文件使用单独的文件传输通道。
- **桌面。** 在目标机仓库根目录运行 `.\.venv\Scripts\python.exe -m pip install -e ".[all]"` 安装桌面依赖。截图支持活动显示器，按键发往前台窗口，需要已登录、已解锁的交互桌面。多人协作时由一人负责桌面输入。
- **多人授权。** 同一实例向连接者提供同一套工具。需要隔离权限时，用不同端口分别运行只读和操作员实例，并让网络规则仅向相应用户开放各自的端口。工业设备的轴运动、伺服参数变更和喷头操作须单独获得操作员授权。

## 故障排查

| 第一个失败的环节 | 到哪里查 |
|---|---|
| 目标机不可达 | 在控制端核对私网、目标地址和共享状态。Tailscale 可单独运行 `tailscale ping <目标机IP>` 检查路由。 |
| TCP 连接失败 | 检查目标进程、监听地址、实际端口及防火墙。回环地址只能在目标机上使用。 |
| TCP 已通，HTTP 超时或连接关闭 | 看目标端控制台及代理日志。管道输出无人读取、控制台选中文本或进程卡住都可能导致超时。连接被关闭时也要查看中间代理和认证设置。 |
| HTTP 有响应，初始化或认证失败 | 核对 URL 的 `/mcp` 路径、Streamable HTTP 传输和服务端认证方式。 |
| `tools/list` 与预期不同 | 核对运行实例的启动参数、客户端连接的端口及预期权限，重新建立 MCP 会话。 |
| 主机名不符、沙箱未配置或截图空白 | 主机名不符时先查目标身份；文件操作前核对运行进程的沙箱设置；截图问题查目标机当前桌面会话。 |

记录失败步骤、实际返回值和仍待核实的字段。完整工具名称与代理执行步骤见[操作技能](../skills/rig-remote-ops/SKILL.md)。
