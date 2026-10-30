"""团队安全: validate / doctor / update / index / migrate 的测试。"""

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.doctor_cmd import doctor_cmd
from team_memory.commands.index_cmd import index_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.commands.update_cmd import update_cmd
from team_memory.commands.validate_cmd import validate_cmd
from team_memory.store import MemoryStore

_QUIET = Console(quiet=True)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="alice")
    return root


def test_validate_clean_repo(tmp_path):
    code = validate_cmd(_init(tmp_path), console=_QUIET)
    assert code == 0  # 种子记忆(新 id)合法


def test_validate_detects_bad_frontmatter(tmp_path):
    root = _init(tmp_path)
    (root / "memory" / "errors" / "broken.md").write_text(
        "no frontmatter", encoding="utf-8"
    )
    assert validate_cmd(root, console=_QUIET) == 1


def test_doctor_reports_and_healthy(tmp_path):
    root = _init(tmp_path)
    assert doctor_cmd(root, console=_QUIET) == 0  # 干净
    (root / "memory" / "errors" / "broken.md").write_text(
        "no frontmatter", encoding="utf-8"
    )
    assert doctor_cmd(root, console=_QUIET) == 1  # 有问题


def test_update_appends_note(tmp_path):
    root = _init(tmp_path)
    capture_cmd("决策A", "decision", author="alice", root=root)
    store = MemoryStore(root=root)
    entry = next(e for e in store.list_entries("decision") if e.title == "决策A")
    update_cmd(entry.id, note="补充要点", root=root, console=_QUIET)
    refreshed = store.get_entry(entry.id)
    assert "补充要点" in refreshed.body
    assert "## 更新" in refreshed.body


def test_update_supersede(tmp_path):
    root = _init(tmp_path)
    capture_cmd("旧决策", "decision", author="alice", root=root)
    capture_cmd("新决策", "decision", author="alice", root=root)
    store = MemoryStore(root=root)
    old = next(e for e in store.list_entries("decision") if e.title == "旧决策")
    new = next(e for e in store.list_entries("decision") if e.title == "新决策")
    update_cmd(old.id, supersede=new.id, root=root, console=_QUIET)
    refreshed = store.get_entry(old.id)
    assert refreshed.status.value == "superseded"
    assert refreshed.superseded_by == new.id


def test_index_generates(tmp_path):
    root = _init(tmp_path)
    capture_cmd("决策A", "decision", author="alice", root=root)
    files = index_cmd(root, console=_QUIET)
    assert any("_index.md" in str(f) for f in files)
    idx = (root / "memory" / "decisions" / "_index.md").read_text(encoding="utf-8")
    assert "决策A" in idx


def test_migrate_ids(tmp_path):
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="alice")
    # 写一条旧格式 id 记忆(含 related 引用待迁移)
    old = root / "memory" / "decisions" / "mem-20260623-001-old.md"
    old.write_text(
        "---\nid: mem-20260623-001\ntype: decision\nscope: team\nauthor: alice\n"
        "created: 2026-06-23\nstatus: active\nrelated: [mem-20260623-002]\n---\n# old\n",
        encoding="utf-8",
    )
    old2 = root / "memory" / "decisions" / "mem-20260623-002-old2.md"
    old2.write_text(
        "---\nid: mem-20260623-002\ntype: decision\nscope: team\nauthor: alice\n"
        "created: 2026-06-23\nstatus: active\n---\n# old2\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, "scripts/migrate-ids.py", str(root)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "mem-20260623-alice-001" in r.stdout
    assert not old.exists()  # 旧文件名已重命名
    # related 引用已更新
    new1 = list((root / "memory" / "decisions").glob("mem-20260623-alice-001*.md"))[0]
    assert "mem-20260623-alice-002" in new1.read_text(encoding="utf-8")
