"""inbox 候选审核机制测试(propose/review/approve/decline) + doctor 过期检查。"""

from pathlib import Path

from rich.console import Console

from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.doctor_cmd import doctor_cmd
from team_memory.commands.inbox_cmd import (
    approve_cmd,
    decline_cmd,
    propose_cmd,
    review_cmd,
)
from team_memory.commands.init_cmd import init_cmd
from team_memory.store import MemoryStore

_QUIET = Console(quiet=True)
_WIDE = Console(width=200)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="alice")
    return root


def test_propose_creates_pending_candidate(tmp_path):
    root = _init(tmp_path)
    path = propose_cmd(
        "候选决策", "decision", author="alice", source="codex",
        confidence="high", evidence=("PR-123", "badcase-456"),
        root=root, console=_QUIET,
    )
    assert path.parent.name == "inbox"
    store = MemoryStore(root=root)
    inbox = store.list_inbox()
    assert len(inbox) == 1
    assert inbox[0].status.value == "pending_review"
    assert inbox[0].confidence == "high"
    assert "PR-123" in inbox[0].evidence
    assert "badcase-456" in inbox[0].evidence


def test_approve_moves_to_formal(tmp_path):
    root = _init(tmp_path)
    propose_cmd("候选", "decision", author="alice", root=root, console=_QUIET)
    store = MemoryStore(root=root)
    cid = store.list_inbox()[0].id
    dest = approve_cmd(cid, root=root, console=_QUIET)
    assert dest.parent.name == "decisions"        # 已移到正式目录
    assert store.list_inbox() == []               # inbox 清空
    entry = store.get_entry(cid)
    assert entry.status.value == "active"         # 状态转 active


def test_decline_keeps_inbox_as_declined(tmp_path):
    root = _init(tmp_path)
    propose_cmd("候选", "error", author="alice", root=root, console=_QUIET)
    store = MemoryStore(root=root)
    cid = store.list_inbox()[0].id
    decline_cmd(cid, root=root, reason="证据不足", console=_QUIET)
    all_inbox = store.list_inbox(status_filter="all")
    assert len(all_inbox) == 1
    assert all_inbox[0].status.value == "declined"
    assert store.list_inbox(status_filter="pending_review") == []  # pending 空


def test_review_lists_pending(tmp_path, capsys):
    root = _init(tmp_path)
    propose_cmd("候选A", "decision", author="alice", source="claude", root=root, console=_QUIET)
    review_cmd(root=root, console=_WIDE)
    out = capsys.readouterr().out
    assert "候选A" in out


def test_doctor_detects_expired(tmp_path):
    root = _init(tmp_path)
    capture_cmd("过期决策", "decision", author="alice", root=root, console=_QUIET)
    store = MemoryStore(root=root)
    entry = store.list_entries("decision")[0]
    f = store.find_file(entry.id)
    text = f.read_text(encoding="utf-8")
    # 注入一个已过期的 expires
    f.write_text(
        text.replace("status: active", "status: active\nexpires: 2020-01-01"),
        encoding="utf-8",
    )
    assert doctor_cmd(root, console=_QUIET) == 1  # 检出过期问题
