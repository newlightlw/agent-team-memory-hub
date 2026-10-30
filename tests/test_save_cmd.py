"""repo_guard 与 save 命令测试。"""

from pathlib import Path

import pytest

from team_memory.commands.init_cmd import init_cmd
from team_memory.gitutil import run_git
from team_memory.commands.save_cmd import save_cmd
from team_memory.repo_guard import assert_valid_memory_repo, looks_like_tool_repo


def test_looks_like_tool_repo():
    root = Path(__file__).resolve().parents[1]
    assert looks_like_tool_repo(root)


def test_assert_valid_memory_repo_rejects_tool_repo():
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="工具仓库"):
        assert_valid_memory_repo(root)


def test_save_cmd_in_memory_repo(tmp_path):
    mem = tmp_path / "team-memory"
    init_cmd(mem, team_name="T", author="bob")
    # A fresh CI runner must not depend on a developer's global Git identity.
    run_git(mem, "config", "user.name", "Synthetic Bob", check=True)
    run_git(mem, "config", "user.email", "synthetic-bob@example.invalid", check=True)
    path = save_cmd(
        "MoE 测试",
        "skill",
        author="bob",
        source="claude",
        note="测试 save 命令",
        root=mem,
    )
    assert path.exists()
    assert "mem-" in path.name
    assert (mem / ".git").exists()
    log = __import__("subprocess").run(
        ["git", "-C", str(mem), "log", "-1", "--oneline"],
        capture_output=True,
        text=True,
    )
    assert "memory(skill): MoE 测试" in log.stdout
