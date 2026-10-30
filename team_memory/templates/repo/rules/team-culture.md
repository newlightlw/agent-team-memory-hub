# 团队文化

## 工作方式

- **AI-assisted**：优先用 AI coding 工具提效，但人对结果负责
- **先文件化后服务化**：能用 Markdown + Git 解决，就不上复杂系统
- **上下文共享**：所有工具读同一套团队记忆，避免重复解释

## 协作

- 重要决策必须沉淀为 ADR（`memory/decisions/`）
- 遇到非平凡错误必须沉淀为 error 记忆（`memory/errors/`）
- 每周 Memory Review：检查过期、冲突、缺失

## 边界

- Agent 可建议写记忆，但**不自动覆盖核心记忆**
- secrets 绝不入库（`.env` 已 gitignore）
- 涉及客户话术 / 合规的更新必须人工审核
