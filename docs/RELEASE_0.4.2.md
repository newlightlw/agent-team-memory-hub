# v0.4.2 — Hermes 升级配置修复

- Hermes 的既有托管 MCP 升级改为替换原映射，避免追加同名 YAML key 后旧版本仍生效。
- 能修复早期托管升级产生的该组件重复 key，保留其他 MCP、设置与注释，升级前备份原文件。
- 升级回归覆盖 Codex、Claude Code、Hermes 三端，以及 Hermes 重复 key 修复。
- 保留 v0.4.1 的后台摘要超时清理、六字段归档与显式启用上传行为。
