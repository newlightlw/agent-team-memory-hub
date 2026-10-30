# Inbox — 候选记忆

这里存放 **AI / 未验证经验**产生的候选记忆（frontmatter `status: pending_review`），等待人工审核后转为正式记忆。

## 工作流

1. AI 或成员用 `team-memory propose "标题" -t <类型> --via <工具>` 提交候选 → 进此目录
2. `team-memory review` 列出待审候选
3. `team-memory approve <id>` 通过 → 自动转入 `memory/{类型}/`（status 变 active）
4. `team-memory decline <id>` 拒绝 → 标 declined（留此供追溯）

## 核心原则

> AI 可以提交 memory candidate，但不能直接写入正式 team memory。

候选记忆建议带 `evidence`（来源证据：PR / 会议 / bad case / eval report）和 `confidence`（low/medium/high），便于审核判断。
