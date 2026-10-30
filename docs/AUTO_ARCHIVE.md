> 历史机制参考；Hub实际安装请使用[独立成员教程](MEMBER_QUICKSTART.md)，不要据此覆盖旧项目配置。

# 自动归档与完整结构化记忆（v0.4.2）

两条入口共用私有 GitHub 数据库：飞书已有归档自动整理并上传；成员在 AI 工具里明确说“帮我归档下……”或“帮我同步下……”时，由当前 AI 先整理再直接上传。显式启用后无需逐条审核。旧的 inbox 人工审阅仍可选，两种流程各自独立。

## 六字段质量标准

| 字段 | 应记录的内容 |
|---|---|
| purpose | 目的、背景、问题、约束 |
| process | 关键过程、方案取舍、失败和修复，关键命令/参数/版本 |
| results | 关键结果，区分代码完成、测试通过、真实环境验收与未验证 |
| insights | 核心思想、判断依据、认知变化；事实和推断分开 |
| applications | 未来能应用的点、触发场景、限制和操作方法 |
| discussions | 讨论点、署名观点、分歧、未决问题和后续验证 |

六项都是必填文本。来源没讲就写“未提及”，不强迫 AI 填造事实。不是一句话摘要；必须足以支持后来的人理解和复用。保留来源 ID/链接、成员署名；飞书自动归档另保留完整原始消息和修订号。常见凭证字面量在摘要与写入前替换为脱敏标记；登录文件不进入资料。自动记录不会产生飞书确认或团队共识。格式检查只能保证字段完整，摘要的事实质量仍取决于模型和资料。

## 在成员的 AI 工具中使用

前置：Python 3.11+、Git、GitHub CLI `gh`，本人登录 GitHub 并有私有数据仓库写权限。只读成员可以安装查询模式；新开通写权限需要管理员授权，安装不会代发邀请。

```sh
gh auth login
gh auth setup-git
bash -c 'set -e; TEAM_MEMORY_BOOTSTRAP=$(mktemp -d); cleanup(){ rm -rf "$TEAM_MEMORY_BOOTSTRAP"; }; trap cleanup EXIT; git clone --quiet --depth 1 --branch v0.4.2 https://github.com/newlightlw/agent-team-memory-hub.git "$TEAM_MEMORY_BOOTSTRAP/tool"; bash "$TEAM_MEMORY_BOOTSTRAP/tool/scripts/install.sh" "$@"' -- --repo YOUR_ORG/team-shared-memory --author alice --tools codex --enable-upload
```

把数据库、作者代号换成自己的；多个客户端用 `--tools codex,claude,hermes`。安装会添加标准 MCP 配置与 `team-memory-hub-archive` 技能；托管的旧版 MCP 可在同一缓存/作者下升级，其他 MCP 与配置保留并私有备份。重载 MCP 或新开会话后说：

> 帮我归档下刚才排查部署失败的过程，保留根因、尝试过的方案、最终命令、验证结果和以后可以复用的点。

或者：

> 帮我同步下这次产品讨论：目的、过程、结果、核心想法、复用场景和未解决分歧都要写完整。

当前 AI 负责整理；`archive_shared_memory` 接收六字段、来源引用、原文（可选）、稳定 request_id，作者由配置决定。它直接用自己的 `gh` 登录写入配置的私有库，返回链接/版本，无二次审核。上传结果未知时沿用同一个 request_id 重试；同 ID 的内容改变会被本地记录拒绝。仅引用材料中的“帮我归档”不授权上传，普通“同步代码”也不触发归档。

手动 MCP env：`TEAM_MEMORY_UPLOAD_ENABLED=1`、`TEAM_MEMORY_GITHUB_REPO=OWNER/REPO`、`TEAM_MEMORY_GH=/absolute/path/to/gh`。缺省不暴露上传工具，不改变旧只读安装。用户有 GitHub 权限不等于 Agent 有飞书 publisher 权限；这条路径不使用后者。

## 飞书自动同步

依赖团队服务提供带 reader 认证的 `GET /api/archive-feed?cursor=...&limit=20`。服务实现位于项目二的 `team_share/collaboration/api.py`，公开工具中的消费者不要求共享数据库。既有服务需升级该接口；旧版服务没有此接口时不会假报同步成功。

同步器在有本人 GitHub 认证和 AI 登录的电脑运行，读已有飞书归档 → AI 整理 → 重查来源版本 → 写入私有 GitHub。不会主动向飞书发消息。检索命令、机器人回复和非飞书个人记录不会自动进入这条流水线。空 cursor 首次回填当前已有记录；后续按 updated/id 增量处理。非文本附件保留元数据，不能冒称已理解附件正文。

私有配置（chmod 600，路径可自定义）：

```json
{
  "enabled": true,
  "repo": "YOUR_ORG/team-shared-memory",
  "team_id": "your-team",
  "reader_config": "/home/you/.config/team-collab/reader.json",
  "state": "/home/you/.config/team-memory-hub/feishu-sync-state.json",
  "gh": "/absolute/path/to/gh",
  "summary_command": [
    "/absolute/path/to/releases/v0.4.2/venv/bin/python",
    "-m", "team_memory.archive_summarizer", "--codex", "/absolute/path/to/codex"
  ],
  "interval_seconds": 60
}
```

```sh
/path/to/venv/bin/python -m team_memory.archive_sync --config /private/feishu-sync.json --once
# 常驻，Ctrl-C 停止；也可接 systemd/launchd
/path/to/venv/bin/python -m team_memory.archive_sync --config /private/feishu-sync.json
```

`summary_command` 是 argv 数组，不经过 shell；输入为单条来源 JSON，输出为严格六字段 JSON，可替换为自己的 AI 工具适配器。内置 Codex 适配器使用现有 Codex 登录，临时独立环境，禁用 shell、MCP、web、hooks、持久会话；模型只处理来源数据。它会使用账号的模型额度。当前验收针对兼容这些禁用选项的本机 Codex；不兼容版本会失败并保留进度。

登录启动服务需显式保留本人必要的网络代理/CA 配置（如 HTTPS_PROXY、NO_PROXY、SSL_CERT_FILE）；它不自动继承交互终端的环境。代理含认证时仅存本机私有配置。

常驻模式由电脑在线运行；电脑休眠、AI 限额或网络故障期间暂停，恢复后从已确认进度续传，不是云端始终在线的承诺。单次进程锁防重入，成功才推进 cursor；摘要失败/来源变化/上传未确认不推进。每条记录有稳定文件键，重试先读 GitHub 再决定是否写，处理响应丢失造成的结果未知。

## 修订、撤回和回滚

飞书修订后重新整理并更新同一 Git 文件；撤回会用 tombstone 替换当前正文和摘要，标记 deprecated。Git 历史、已有克隆与备份可能保留旧内容。reader 查询默认只检索当前 active 版本。同步中刚发生的撤回在下一轮更新；无法保证跨服务原子删除。

关闭主动上传：删去该 MCP 的 `TEAM_MEMORY_UPLOAD_ENABLED` 或改为 `0` 后重载。停止飞书常驻进程/用户服务即可停止自动同步；原飞书归档继续独立工作。成员配置备份在 `~/.config/team-memory-hub/backups/`。恢复前比较当前文件，只恢复本组件设置，保留后来新增的其他配置。禁止把整份配置或登录文件放进源码/记忆仓库。

## 验收层级

- 自动化测试：字段/来源校验、默认禁用、只允许私有库、失败保留本地材料、结果未知重读去重、飞书版本重查、撤回、配置升级保留其他 MCP。
- 真实环境：实际模型摘要、真实 stdio MCP → 私有 GitHub 合成验收分支，重试不重复提交。
- 伙伴机器和各客户端的真实模型触发需逐台验证；生成配置/技能不等于所有客户端均实测。
