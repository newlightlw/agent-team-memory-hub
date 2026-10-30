# v0.4.0 — 结构化归档与飞书自动同步

- 新增显式启用的 archive_shared_memory：当前 AI 先整理目的、关键过程、结果、核心思想、应用场景、讨论点，再直接写入私有 GitHub。
- 一键安装器 --enable-upload 安装 Codex/Claude Code/Hermes 的触发技能与上传配置；默认查询安装保持只读。
- 新增飞书增量 feed 消费者，AI 摘要完成后保留原文、作者和来源版本；来源重查、失败续传、去重与当前版本撤回。
- 内置零工具 Codex 摘要适配器；summary_command 可替换其他工具。
- GitHub Contents API 只修改目标记录，不执行 blanket add/commit，不读取飞书 publisher 凭证，也不代替真人确认。

使用方法、接入条件、回滚与限制见 [自动归档指南](AUTO_ARCHIVE.md)。飞书 feed 属于独立团队服务，需升级服务接口；公开成员工具不携带私有服务配置。
