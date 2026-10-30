"""Team Memory — 团队 Agent Memory 共享系统。

把 Cursor / Claude Code / Codex / Hermes 等工具中的记忆统一汇聚到 Git 仓库,
让团队成员可以加载团队记忆并沉淀经验。

设计原则:
  - 工作记忆 -> 精选长期记忆(本仓库) -> 完整历史 -> 外部知识源
  - 新写入不在当前 session 生效(写入走 Git, 下个会话才加载)
  - 外部召回不写回历史
  - 判断信息存哪一层, 比存得更聪明更重要

Phase 1 走纯 Git 路线(Markdown + frontmatter), 不依赖向量数据库。
"""

__version__ = "0.5.0rc1"
