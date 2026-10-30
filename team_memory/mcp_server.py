"""team-memory MCP Server — 让 AI 工具通过 MCP 协议动态读写团队记忆。

启动: python -m team_memory.mcp_server
配置: 环境变量 TEAM_MEMORY_ROOT=<记忆仓库路径>(不设则从 cwd 向上自动定位)

暴露的 tools:
  search_memory(query)         关键字搜索
  get_memory(id)               单条详情(含版本历史)
  list_memories(type?)         列正式记忆
  propose_memory(title, type)  提交候选到 inbox(AI 经验, 待审核)
  list_inbox(status?)          列候选记忆
  approve_memory(id)           候选 → 正式

原则: AI 可 propose(候选), 但不直接写正式记忆; approve 由人触发。
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from rich.console import Console

from .store import MemoryStore

mcp = FastMCP("team-memory")
# MCP server 的 stdout 是 JSON-RPC 通道, 必须静默所有 console 输出
_QUIET = Console(quiet=True)


def _store() -> MemoryStore:
    """定位记忆仓库(env TEAM_MEMORY_ROOT 或从 cwd 向上自动找 .team-memory.yml)。"""
    root = os.environ.get("TEAM_MEMORY_ROOT")
    if root:
        return MemoryStore.open(Path(root))
    return MemoryStore.open()


@mcp.tool()
def search_memory(query: str, top_k: int = 10) -> list[dict]:
    """关键字搜索团队记忆(匹配标题/正文/标签/作者/来源/id), 返回最相关条目。"""
    from .web.server import search_memories

    store = _store()
    return search_memories(store, query)[:top_k]


@mcp.tool()
def get_memory(memory_id: str) -> dict:
    """按 id 获取单条记忆详情(含正文、版本历史 commits、关联 related)。"""
    from .web.server import _entry_to_dict

    store = _store()
    entry = store.get_entry(memory_id)
    if entry is None:
        return {"error": f"未找到记忆: {memory_id}"}
    return _entry_to_dict(store, entry)


@mcp.tool()
def list_memories(type: str = "") -> list[dict]:
    """列出正式记忆; type 可选过滤(project/code/decision/error/skill)。"""
    from .web.server import list_memories as web_list_memories

    store = _store()
    return web_list_memories(store, type or None, None)


@mcp.tool()
def propose_memory(
    title: str,
    type: str,
    source: str = "",
    author: str = "",
    confidence: str = "medium",
    note: str = "",
) -> dict:
    """提交候选记忆到 inbox(status=pending_review, 待人工 approve)。

    用于 AI 产出/未验证的经验: 先进 inbox, 不直接写正式记忆。
    type: project/code/decision/error/skill; source: claude/codex/hermes/trae。
    """
    from .commands.inbox_cmd import propose_cmd
    from .models import parse_memory

    store = _store()
    path = propose_cmd(
        title, type, source=source, author=author,
        confidence=confidence, note=note, root=store.root,
        console=_QUIET,
    )
    entry_id = parse_memory(path.read_text(encoding="utf-8")).id
    return {"ok": True, "id": entry_id, "path": str(path),
            "hint": "待审核: approve_memory(id) 通过, 或人工 team-memory approve"}


@mcp.tool()
def list_inbox(status: str = "pending_review") -> list[dict]:
    """列出 inbox 候选记忆(默认 pending_review; status='all' 列全部含 declined)。"""
    from .web.server import _entry_to_dict

    store = _store()
    return [
        _entry_to_dict(store, e) for e in store.list_inbox(status_filter=status)
    ]


def approve_memory(memory_id: str) -> dict:
    """通过候选记忆 → 自动转为正式记忆(inbox 移到 memory/{type}/, status=active)。"""
    from .commands.inbox_cmd import approve_cmd

    store = _store()
    path = approve_cmd(memory_id, root=store.root, console=_QUIET)
    return {"ok": True, "id": memory_id, "path": str(path)}


if __name__ == "__main__":
    mcp.run()
