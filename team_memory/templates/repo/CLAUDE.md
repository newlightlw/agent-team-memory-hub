# {team_name} Agent 记忆中心

本仓库是 **{team_name}** 团队的共享记忆系统。所有 AI Agent 会话都会加载本文件。

## Agent 启动指令

在任何项目会话中：

1. 先读本文件
2. 读 `rules/` 下的团队规范
3. 若在具体项目中，读该项目的 `CLAUDE.md` / `AGENTS.md` / `.cursor/rules`
4. 做重要变更前，先查 `memory/decisions/` 中相关 ADR
5. 解决非平凡问题后，用 `templates/` 模板沉淀记忆
   — 但**不要在当前会话立即依赖新写入的记忆**（写入后下个会话才加载，避免污染当前对话）

## 团队身份

- 团队：{team_name}
- 业务：AI 驱动的对话系统（话术 Agent OS）

## 五类记忆速查

| 类型 | 位置 | 何时读取 | 何时写入 |
|------|------|----------|----------|
| 项目 | `memory/project/` | 接手新任务时 | 项目范围变化时 |
| 代码 | `memory/code/` | 写代码前 | 发现重要结构时 |
| 决策 | `memory/decisions/` | 做技术选择前 | 做出重要决策后 |
| 错误 | `memory/errors/` | 遇到错误时 | 解决非平凡错误后 |
| Skill | `memory/skills/` | 执行流程前 | 验证可复用流程后 |

## 记忆写入规范

1. 不要在任务执行中写记忆——任务完成后再写
2. 使用 `templates/` 下的标准模板
3. 填写 `author` 和 `role` 字段
4. 添加 `related` 关联到相关记忆
5. 走 PR 审核
6. 废弃不删除——更新 `status` 字段并链接到新记忆

## 仓库索引

- 决策(ADR)：`memory/decisions/`
- 错误：`memory/errors/`
- Skill：`memory/skills/`

## 工具桥接

各工具通过项目内的桥接文件读取本仓库（由 `team-memory load` 生成）：

- **Claude Code**：项目根 `CLAUDE.md`
- **Codex**：项目根 `AGENTS.md`
- **Cursor**：项目根 `.cursor/rules/memory.mdc`
- **Hermes**：`~/.hermes/skills/team-memory/`
