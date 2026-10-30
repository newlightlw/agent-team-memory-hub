# 兼容矩阵（v0.5.0-candidate.1候选）

| 范围 | 支持目标 | 当前证据 |
|---|---|---|
| 成员端 | macOS/Linux、Python3.11+ | 本机macOS Python3.12实际测试；其余待托管CI |
| 服务端 | Ubuntu24.04、Python3.12、systemd、Nginx | 源码/生成脚本与本机wheel验证；独立Ubuntu部署未执行 |
| Codex摘要 | 必须支持ignore-user-config、ignore-rules、ephemeral、disable、output-schema、sandbox | 当前本机CLI兼容探测及真实模型通过；版本字段见validation/inherited-selfhost-candidate/runtime-versions.json |
| Claude摘要 | 必须支持safe-mode、tools、strict-mcp-config、setting-sources、no-session-persistence、json-schema | 当前本机CLI真实模型通过；仅Schema输出工具，不允许执行工具 |
| GitHub成员查询/上传 | 自己账号、私有数据仓库、上传需Write | stdio MCP→独立私有GitHub合成验收通过 |
| 网页 | HTTPS、独立账号、只读内容 | 认证与停用/重置自动化通过；候选新域名实际部署待验收 |
| v0.4.2 | 旧标签及旧成员接口 | 保留；不自动升级已安装实例 |
| 配置v1 | 可加载，显式迁移v2先备份 | 自动化兼容通过，不自动改写旧生产 |
| Windows/其他MCP客户端 | 不列入首版一键实测承诺 | 未验证 |

发现CLI安全选项不足时保持摘要禁用；不以删除安全参数获取兼容。不同CLI版本可能改变输出，必须重做真实模型审计。
