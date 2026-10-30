"""MCP Server tools 测试(直接调 tool 函数, 不经 stdio)。"""

from pathlib import Path

from team_memory import mcp_server
from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.store import MemoryStore


def _setup(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="alice")
    monkeypatch.setenv("TEAM_MEMORY_ROOT", str(root))
    capture_cmd("测试决策A", "decision", author="alice", root=root)
    return root


def test_mcp_search(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    results = mcp_server.search_memory("测试")
    assert len(results) >= 1
    assert any("测试决策A" in r["title"] for r in results)


def test_mcp_get_and_list(tmp_path, monkeypatch):
    root = _setup(tmp_path, monkeypatch)
    store = MemoryStore.open(root)
    eid = store.list_entries("decision")[0].id
    got = mcp_server.get_memory(eid)
    assert got["id"] == eid
    assert "commits" in got
    assert len(mcp_server.list_memories()) >= 1
    assert len(mcp_server.list_memories("decision")) >= 1


def test_mcp_propose_approve_flow(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # AI 提交候选
    r = mcp_server.propose_memory("候选X", "decision", source="codex", author="alice")
    assert r["ok"]
    cid = r["id"]
    # inbox 有 1 条 pending
    inbox = mcp_server.list_inbox()
    assert len(inbox) == 1
    assert inbox[0]["id"] == cid
    assert inbox[0]["status"] == "pending_review"
    # approve → 正式
    a = mcp_server.approve_memory(cid)
    assert a["ok"]
    assert mcp_server.list_inbox() == []          # inbox 空
    assert mcp_server.get_memory(cid)["status"] == "active"
