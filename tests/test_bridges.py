"""bridges 的测试 — 用临时 home, 不污染真实 ~/.claude / ~/.codex 等。"""

from pathlib import Path

import pytest

from team_memory.bridges import GLOBAL_BRIDGES, is_tool_installed
from team_memory.bridges.claude import bridge_claude
from team_memory.bridges.codex import bridge_codex
from team_memory.bridges.common import MARKER_END, MARKER_START, update_marked_section
from team_memory.bridges.hermes import bridge_hermes
from team_memory.bridges.trae import bridge_trae
from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.config import load_config
from team_memory.store import MemoryStore


def _setup(tmp_path: Path):
    root = tmp_path / "repo"
    init_cmd(root, team_name="测试团队", author="alice")
    capture_cmd("采用纯Git路线", "decision", author="alice", root=root)
    store = MemoryStore.open(root)
    config = load_config(env_path=root / ".env")
    return store, config


def test_registry_has_four_tools():
    assert set(GLOBAL_BRIDGES) == {"claude", "codex", "hermes", "trae"}
    assert is_tool_installed("unknown-tool") is False


@pytest.mark.parametrize(
    "bridge_fn",
    [bridge_claude, bridge_hermes, bridge_trae],
    ids=["claude", "hermes", "trae"],
)
def test_skill_bridges_write_correct_skill(tmp_path, bridge_fn):
    store, config = _setup(tmp_path)
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()

    path = bridge_fn(store, config, home=fake_home)
    assert path is not None
    assert path == fake_home / "skills" / "team-memory" / "SKILL.md"

    text = path.read_text(encoding="utf-8")
    # Hermes/Claude/Trae skill 都用 YAML frontmatter
    assert text.startswith("---")
    assert "name: team-memory" in text
    assert "测试团队" in text
    # listing 应含已沉淀的记忆标题
    assert "采用纯Git路线" in text


def test_codex_bridge_idempotent_and_preserves_user_content(tmp_path):
    store, config = _setup(tmp_path)
    fake_home = tmp_path / "codexhome"
    fake_home.mkdir()
    # 模拟用户在 AGENTS.md 里已有的内容
    agents = fake_home / "AGENTS.md"
    agents.write_text("# 我的原有指令\n\n保留这段。\n", encoding="utf-8")

    bridge_codex(store, config, home=fake_home)
    text1 = agents.read_text(encoding="utf-8")
    assert "保留这段" in text1  # 用户原有内容保留
    assert MARKER_START in text1 and MARKER_END in text1
    assert "测试团队" in text1  # team-memory 段已写入

    # 再跑一次: marker 段不重复, 用户内容仍在
    bridge_codex(store, config, home=fake_home)
    text2 = agents.read_text(encoding="utf-8")
    assert text2.count(MARKER_START) == 1
    assert text2.count(MARKER_END) == 1
    assert "保留这段" in text2


def test_bridge_skips_when_home_missing(tmp_path):
    store, config = _setup(tmp_path)
    # home 不存在 -> 跳过, 返回 None(不抛错)
    assert bridge_claude(store, config, home=tmp_path / "nope") is None
    assert bridge_codex(store, config, home=tmp_path / "nope") is None


def test_update_marked_section_replaces_not_duplicates(tmp_path):
    target = tmp_path / "AGENTS.md"
    update_marked_section(target, "第一版内容")
    update_marked_section(target, "第二版内容")
    text = target.read_text(encoding="utf-8")
    assert "第二版内容" in text
    assert "第一版内容" not in text  # 旧段被替换
    assert text.count(MARKER_START) == 1
