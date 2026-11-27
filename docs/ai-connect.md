# 让 AI 验收 rig-gateway 连接

[中文首页](../README.md) · [English](ai-connect.en.md) · [人工操作手册](operations.md)

适用于能调用 MCP 工具或运行本地 Python 的 AI。已有网关配置时，直接复制下面的提示词。若需新建连接，可同时提供目标私网地址、实际端口、预期权限级别和独立确认的 Windows 主机名。

## 首次连接验收

```text
请用中文验收 rig-gateway。此次只做工具发现和只读状态查询。

优先使用已有 MCP 配置。取得这个服务器的完整 tools/list，调用 system_info 和 host_status。用仓库 skills/rig-remote-ops/SKILL.md 的工具名称表核对预期级别。默认预期是 Tier 1。若客户端只展示部分清单，标记“权限级别未核实”。

若没有已配置的 MCP 连接，但已知目标是直连的私网 HTTP 网关，从控制端仓库根目录运行：
python skills/rig-remote-ops/scripts/verify_endpoint.py --host <目标地址> --port <实际端口> --auth none --tier <预期级别> --expect-hostname <已知目标机名>
替换占位符。未知预期机名时省略整个 --expect-hostname 参数，将身份标为“待确认”。需要 HTTPS、mTLS 或代理认证时沿用已配置的客户端，凭据留在客户端。缺少目标地址时向我询问。

报告连接是否成功、实际主机名与身份核对结果、工具数和预期级别是否匹配、沙箱路径。原样保留未配置状态。若出现差异，报告第一个失败的步骤、预期值、实际值和下一项检查。不要用实际返回值改写预期后重试。部署、重启、写文件、远程命令和桌面输入留待单独授权。
```
