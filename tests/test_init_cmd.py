"""init_cmd 的测试 — 记忆仓库骨架生成。"""

from pathlib import Path

from team_memory.commands.init_cmd import init_cmd
from team_memory.store import MARKER_FILE, MemoryStore


def test_init_creates_full_structure(tmp_path):
    root = tmp_path / "repo"
    init_cmd(root, team_name="测试团队", author="alice")

    # 标记 + 骨架
    assert (root / MARKER_FILE).exists()
    assert (root / "CLAUDE.md").exists()
    assert (root / "README.md").exists()
    assert (root / "rules" / "team-culture.md").exists()
    assert (root / "rules" / "code-standards.md").exists()
    # 五类记忆的 body 模板
    assert (root / "memory" / "decisions" / "_template.md").exists()
    assert (root / "memory" / "errors" / "_template.md").exists()
    assert (root / "memory" / "skills" / "_template.md").exists()
    # 种子记忆 + .env
    assert (root / "memory" / "project" / "product-overview.md").exists()
    assert (root / ".env").exists()
    # team_name 变量渲染
    assert "测试团队" in (root / "README.md").read_text(encoding="utf-8")
    # git 初始化
    assert (root / ".git").exists()
    # 可作为 MemoryStore 打开
    store = MemoryStore.open(root)
    assert store.root == root.resolve()


def test_init_is_idempotent(tmp_path):
    root = tmp_path / "repo"
    init_cmd(root, team_name="T", author="a")
    # 第二次(不 force)不应崩溃, 也不应覆盖已有内容
    readme_before = (root / "README.md").read_text(encoding="utf-8")
    init_cmd(root, team_name="T2", author="a")  # 换了 team_name
    readme_after = (root / "README.md").read_text(encoding="utf-8")
    assert readme_before == readme_after  # 未 force 时保留旧内容
