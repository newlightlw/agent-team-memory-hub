"""list_cmd / show_cmd 的测试。"""

import pytest
from rich.console import Console

from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.commands.list_cmd import list_cmd, show_cmd
from team_memory.store import MemoryStore


def _init(tmp_path):
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="a")
    return root


def test_list_shows_entries_and_sources(tmp_path, capsys):
    root = _init(tmp_path)
    capture_cmd("决策A", "decision", author="v", source="claude", root=root)
    capture_cmd("Think Tank", "project", author="v", source="codex", root=root)
    list_cmd(root, console=Console(width=300))
    out = capsys.readouterr().out
    assert "决策A" in out
    assert "Think Tank" in out
    assert "claude" in out
    assert "codex" in out


def test_show_entry_details(tmp_path, capsys):
    root = _init(tmp_path)
    capture_cmd("决策A", "decision", author="v", source="claude", root=root)
    store = MemoryStore(root=root)
    entry = next(e for e in store.list_entries("decision") if e.title == "决策A")
    show_cmd(entry.id, root)
    out = capsys.readouterr().out
    assert entry.id in out
    assert "决策A" in out
    assert "claude" in out
    assert "版本历史" in out  # 即使未提交也显示该节


def test_show_missing_raises(tmp_path):
    root = _init(tmp_path)
    with pytest.raises(ValueError):
        show_cmd("mem-00000000-999", root)
