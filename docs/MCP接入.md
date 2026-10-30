# MCP Server 接入 — 让 AI 工具动态读写团队记忆

> 对应 Gateway 方案 v0.3。MCP（Model Context Protocol）让 AI 工具通过标准协议
> 动态 search/get/propose 记忆，不再依赖 skill 静态快照或人工跑 CLI。

## 是什么

team-memory 内置一个 MCP Server（`team_memory/mcp_server.py`），暴露 5 个旧版 tools（新 GitHub 接入请用 shared_mcp）。
配好后，Claude Code / Cursor / Codex / Hermes 在对话中能**直接调用**这些工具
读写团队记忆（读：search/get/list；写候选：propose；审核：approve）。

## 启动

```bash
python -m team_memory.mcp_server
# 需环境变量 TEAM_MEMORY_ROOT 指向记忆仓库; 不设则从 cwd 向上找 .team-memory.yml
```

## 配置各工具

### Claude Code

```bash
# 命令行注册(推荐)
claude mcp add team-memory \
  -e TEAM_MEMORY_ROOT=/path/to/team-memory \
  -- python -m team_memory.mcp_server
```

或编辑 `~/.claude.json`（或项目 `.mcp.json`）的 `mcpServers`：
```json
{
  "mcpServers": {
    "team-memory": {
      "command": "python",
      "args": ["-m", "team_memory.mcp_server"],
      "env": {"TEAM_MEMORY_ROOT": "/path/to/team-memory"}
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json`（或项目 `.cursor/mcp.json`）：
```json
{
  "mcpServers": {
    "team-memory": {
      "command": "python",
      "args": ["-m", "team_memory.mcp_server"],
      "env": {"TEAM_MEMORY_ROOT": "/path/to/team-memory"}
    }
  }
}
```

### Codex

`~/.codex/config.toml`：
```toml
[mcp_servers.team-memory]
command = "python"
args = ["-m", "team_memory.mcp_server"]
[mcp_servers.team-memory.env]
TEAM_MEMORY_ROOT = "/path/to/team-memory"
```

### Hermes

`~/.hermes/config.yaml` 的 mcp 段（参考 Hermes MCP 文档，格式同上）。

> Windows：`command` 用 `python`（不是 `python3`）。

## 可用 tools

| Tool | 作用 | 写正式? |
|---|---|---|
| `search_memory(query, top_k=10)` | 关键字搜索（全字段） | 只读 |
| `get_memory(id)` | 单条详情 + 版本历史 + 关联 | 只读 |
| `list_memories(type?)` | 列正式记忆 | 只读 |
| `propose_memory(title, type, source, author)` | **提交候选到 inbox**（pending_review） | 写候选 |
| `list_inbox(status?)` | 列候选记忆 | 只读 |
| `真人终端 team-memory approve（非 MCP）(id)` | 候选 → 正式（active） | 写正式 |

## 核心原则

> **AI 可 propose（候选），但不直接写正式记忆；approve 由人触发**（或人明确授权 AI 调 `真人终端 team-memory approve（非 MCP）`）。

这样既给 AI 动态贡献记忆的能力，又保留人工审核把关，防止 AI 错误经验污染正式记忆。

## 与其他接入方式的关系

| 方式 | 场景 |
|---|---|
| **MCP Server**（本文件） | AI 工具在对话中动态查/写（最灵活） |
| 全局 skill（`load --global`） | 启动时加载团队上下文（静态快照） |
| CLI（`capture`/`propose`） | 人工命令行操作 |
| Web UI（`web`） | 浏览器可视化 + 检索 |

四种方式可组合使用，都指向同一个 Git 记忆仓库。
