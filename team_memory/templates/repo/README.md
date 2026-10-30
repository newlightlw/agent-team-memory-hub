# {team_name} 团队记忆

这是 **{team_name}** 团队的共享记忆仓库。所有 AI coding 工具（Claude Code / Cursor / Codex / Hermes）和团队成员读同一套上下文。

## 这是什么

- 团队认知的**压缩包**，不是聊天记录
- 用 Git 管理：可版本、可审核、可回滚
- 写入走人工审核，不自动覆盖核心记忆

## 五类记忆

| 类型 | 目录 | 何时读 | 何时写 |
|------|------|--------|--------|
| project | `memory/project/` | 接手任务时 | 项目范围变化时 |
| code | `memory/code/` | 写代码前 | 发现重要结构时 |
| decision | `memory/decisions/` | 做技术选择前 | 做出重要决策后 |
| error | `memory/errors/` | 遇到错误时 | 解决非平凡错误后 |
| skill | `memory/skills/` | 执行流程前 | 验证可复用流程后 |

## 怎么用（team-memory CLI）

```bash
team-memory capture "标题" -t decision -p .    # 沉淀一条记忆
team-memory load --global -p .                 # 加载到本机 AI 工具
team-memory sync -p .                          # 同步到 Git 远端
```

## 修改规则

1. 不允许 Agent 自动覆盖核心记忆（project / decisions）
2. Agent 可提出更新建议（沉淀为 capture 草稿）
3. 重要修改走 PR
4. **废弃不删除**：更新 `status: superseded` + `superseded_by` 链接到新记忆
5. 代码与记忆冲突时，先暴露冲突，不直接覆盖

## 记忆字段

见任意记忆文件的 frontmatter：`id` / `type` / `scope` / `author` / `role` / `created` / `updated` / `expires` / `status` / `tags` / `related`。
