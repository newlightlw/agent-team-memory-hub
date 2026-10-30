"""store.py 的测试 — 记忆仓库定位 + CRUD。"""

from pathlib import Path

import pytest

from team_memory.models import MemoryEntry, MemoryType
from team_memory.store import MARKER_FILE, MemoryStore, NotAMemoryRepoError, find_memory_root


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "mem"
    root.mkdir()
    (root / MARKER_FILE).write_text("team_name: t\n", encoding="utf-8")
    return root


def _entry(mid: str, title: str = "x", mtype=MemoryType.DECISION) -> MemoryEntry:
    return MemoryEntry(
        id=mid, type=mtype, title=title, author="v",
        created="2026-06-23", body=f"# {title}\n",
    )


def test_open_missing_marker_raises(tmp_path):
    with pytest.raises(NotAMemoryRepoError):
        MemoryStore.open(tmp_path)


def test_save_writes_to_correct_dir(tmp_path):
    root = _make_repo(tmp_path)
    store = MemoryStore(root=root)
    path = store.save_entry(_entry("mem-20260623-001", "d1"))
    assert path.exists()
    assert path.parent.name == "decisions"
    assert path.name.startswith("mem-20260623-001")


def test_get_and_list(tmp_path):
    root = _make_repo(tmp_path)
    store = MemoryStore(root=root)
    store.save_entry(_entry("mem-20260623-001", "d1", MemoryType.DECISION))
    store.save_entry(_entry("mem-20260623-002", "e1", MemoryType.ERROR))

    assert store.get_entry("mem-20260623-001").title == "d1"
    assert store.get_entry("nope") is None
    assert len(store.list_entries()) == 2
    assert len(store.list_entries("decision")) == 1
    assert len(store.list_entries("error")) == 1


def test_next_id_increments_per_author(tmp_path):
    root = _make_repo(tmp_path)
    store = MemoryStore(root=root)
    # alice 的序号独立于 bob(每人独立空间, 防撞号)
    assert store.next_id("20260623", "alice") == "mem-20260623-alice-001"
    store.save_entry(_entry("mem-20260623-alice-001"))
    store.save_entry(_entry("mem-20260623-bob-001", mtype=MemoryType.ERROR))
    assert store.next_id("20260623", "alice") == "mem-20260623-alice-002"
    assert store.next_id("20260623", "bob") == "mem-20260623-bob-002"
    assert store.next_id("20260624", "alice") == "mem-20260624-alice-001"  # 不同日重置
    # author 空/纯非 ascii → 报错
    with pytest.raises(ValueError):
        store.next_id("20260623", "")
    with pytest.raises(ValueError):
        store.next_id("20260623", "张三")


def test_check_unique_and_parse_errors(tmp_path):
    root = _make_repo(tmp_path)
    store = MemoryStore(root=root)
    # 两条不同文件同 id
    store.save_entry(_entry("mem-20260623-alice-001", "d1"))
    # 手动再写一个同 id 的文件(模拟冲突)
    dup = root / "memory" / "errors" / "mem-20260623-alice-001-dup.md"
    dup.parent.mkdir(parents=True, exist_ok=True)
    dup.write_text(
        "---\nid: mem-20260623-alice-001\ntype: error\nscope: team\nauthor: alice\n"
        "created: 2026-06-23\nstatus: active\n---\n# dup\n", encoding="utf-8"
    )
    dupes = store.check_unique()
    assert "mem-20260623-alice-001" in dupes
    assert len(dupes["mem-20260623-alice-001"]) == 2

    # 坏 frontmatter 文件被 list_parse_errors 捕获(不再静默)
    bad = root / "memory" / "errors" / "broken.md"
    bad.write_text("没有 frontmatter 的纯文本", encoding="utf-8")
    errs = store.list_parse_errors()
    assert any("broken.md" in str(p) for p, _ in errs)


def test_non_memory_files_ignored(tmp_path):
    root = _make_repo(tmp_path)
    store = MemoryStore(root=root)
    # 放一个非 mem- 开头的模板文件, 应被忽略
    tmpl = root / "memory" / "decisions" / "_template.md"
    tmpl.parent.mkdir(parents=True, exist_ok=True)
    tmpl.write_text("模板内容", encoding="utf-8")
    assert store.list_entries() == []


def test_find_memory_root_walks_up(tmp_path, monkeypatch):
    root = _make_repo(tmp_path)
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert find_memory_root() == root.resolve()
