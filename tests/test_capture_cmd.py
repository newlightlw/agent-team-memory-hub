"""capture_cmd 的测试 — 记忆沉淀。"""

from pathlib import Path

import pytest

from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.store import MemoryStore


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="alice")
    return root


def test_capture_decision_uses_template(tmp_path):
    root = _init(tmp_path)
    path = capture_cmd("采用纯Git路线", "decision", author="alice", root=root)
    assert path.exists()
    assert path.parent.name == "decisions"

    store = MemoryStore(root=root)
    decisions = store.list_entries("decision")
    assert len(decisions) == 1
    entry = decisions[0]
    assert entry.title == "采用纯Git路线"
    assert entry.author == "alice"
    assert entry.body.startswith("# 采用纯Git路线")
    # 文件内含标题
    assert "采用纯Git路线" in path.read_text(encoding="utf-8")


def test_capture_next_id_increments(tmp_path):
    root = _init(tmp_path)
    p1 = capture_cmd("d1", "decision", root=root)
    p2 = capture_cmd("d2", "decision", root=root)
    assert "-001" in p1.name
    assert "-002" in p2.name


def test_capture_seed_and_new_coexist(tmp_path):
    root = _init(tmp_path)
    capture_cmd("d1", "decision", root=root)
    store = MemoryStore(root=root)
    # 1 条种子(project) + 1 条新(decision)
    assert len(store.list_entries()) == 2


def test_capture_with_note(tmp_path):
    root = _init(tmp_path)
    path = capture_cmd("某错误", "error", note="这是一条简短记录", root=root)
    text = path.read_text(encoding="utf-8")
    assert "这是一条简短记录" in text
    assert "# 某错误" in text  # body 含标题(frontmatter 在前)


def test_capture_bad_type_raises(tmp_path):
    root = _init(tmp_path)
    with pytest.raises(ValueError):
        capture_cmd("x", "unknown-type", root=root)
