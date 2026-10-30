# v0.3.0 迭代与迁移记录

本版沿用 MIT 许可证，继续维护现有 agent-team-memory，不引入个人 Agent 调度或第四个产品。

## 核对结果

原 GitHub v0.2.3 干净代码的 58 项测试通过。它们没有覆盖全部分发与安装场景；以下问题通过实际操作复现后修复：

- wheel 缺少 templates：原来只在源码相邻目录找模板，安装后的初始化不完整。模板移到 `team_memory/templates/`，随 wheel 分发；自定义扩展请读取 `team_memory.templating.TEMPLATES_DIR`。
- 旧同步流程部分 pull 失败仍可能继续 push：改为失败即停止、只接受 fast-forward，不自动 stash/rebase/reset、提交或 force-push。
- 连续待审核候选的 ID 可能碰撞：编号同时考虑正式记录和 inbox，避免覆盖另一个候选。
- 旧 onboard 不检查每步返回码，失败后仍可能宣布成功：替换为有预检、失败即停止的隔离安装器。

## 新增能力

- GitHub 私有长期知识仓库的只读成员缓存，保留作者、状态与明确的 Git 提交。
- 独立 `team_memory_hub` MCP：三种查询工具与一种本机草稿工具，没有审核、push 或远程发布工具。
- 按需只读同步；失败明确报告 stale，保留本地提交和用户改动。
- 本人选择团队服务中的单条记录，以 reader 生成私有草稿；来源作者、ID、修订号、状态与摘要保留，真人 submit 前重新核查。
- macOS/Linux 一条命令安装：独立 Python 环境、哈希锁依赖、Codex/Claude/Hermes 的增量 MCP 配置和私有备份；不覆盖旧 team-memory 命令。

## 兼容性变化

- `REMOTE_URL` 为新的通用配置名，保留 `GITEA_REMOTE_URL` 作为兼容别名；没有显式配置时使用已有 origin。
- 不再把 `GITEA_TOKEN` 注入并保存到 remote URL。请改用 `gh auth setup-git`、系统 Git credential helper 或本人 SSH key，并清理旧的带凭证 URL。
- 旧 MCP 中的 approve_memory 不再注册为可调用工具；审核通过真人终端 CLI 完成。旧 Git 原生 CLI/Web/候选流程保留。
- 新 member cache 不能当可写编辑仓库。编辑使用另一个经本人核对的 writer checkout；旧可写目录不会被安装器静默转换或覆盖。
- 旧 `scripts/onboard.py REPO author` 现在进入新成员安装流程；它默认不批量安装 auto-commit skill。GitHub 路线的详细步骤以 [新指南](GITHUB_SHARING.md) 为准。

## 验证与限制

本地 72 项测试通过，含真实 Git 双克隆、分叉拒绝、只读写保护、配置幂等、来源草稿与真实 stdio MCP。独立 wheel 安装通过，包含隐藏模板文件，可在新环境初始化并生成候选。CI 不需要个人或生产凭证。

默认 GitHub 主分支只建立目录与流程说明，不捏造真实团队知识。飞书原档案、真人共识和 Git 长期副本仍有不同权威边界。没有给未获授权的成员自动发邀请，也没有把服务器配置、聊天原文或个人凭证上传。

Git 不是强撤回系统，远端历史和其他人的克隆可能保留旧正文。Windows 一键接入未作为本轮真实环境验收，不冒称已经通过；任意客户端安装成功也不自动证明该客户端已重载 MCP 或模型已实际使用。
