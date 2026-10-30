"""bridges_doctor 测试。"""

import json
from pathlib import Path

from team_memory.commands.bridges_doctor_cmd import _read_settings_hooks, bridges_doctor_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.bridges.common import write_skill


def test_read_settings_hooks_detects_team_memory_command(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "onMessage": [{"match": "提交", "command": "team-memory capture"}]
                }
            }
        ),
        encoding="utf-8",
    )
    assert _read_settings_hooks(settings) == ["team-memory capture"]


def _patch_claude_home(monkeypatch, fake_claude, tmp_path):
    import importlib

    bd = importlib.import_module("team_memory.commands.bridges_doctor_cmd")
    monkeypatch.setattr(
        bd, "default_home", lambda tool: fake_claude if tool == "claude" else tmp_path / tool
    )


def test_bridges_doctor_reports_missing_skills(tmp_path, monkeypatch):
    mem = tmp_path / "team-memory"
    fake_claude = tmp_path / "claude-home"
    fake_claude.mkdir()
    init_cmd(mem, team_name="T", author="bob")
    _patch_claude_home(monkeypatch, fake_claude, tmp_path)

    code = bridges_doctor_cmd(mem, tools=("claude",), console=None)
    assert code >= 1  # missing auto-commit skill


def test_bridges_doctor_ok_when_skills_installed(tmp_path, monkeypatch):
    mem = tmp_path / "team-memory"
    fake_claude = tmp_path / "claude-home"
    fake_claude.mkdir()
    init_cmd(mem, team_name="T", author="bob")
    root = str(mem.resolve())
    write_skill(
        fake_claude,
        "team-memory",
        f"memory repo: {root}",
    )
    write_skill(
        fake_claude,
        "auto-commit-memory",
        f'memory root {root}\n{root}\npython -m team_memory save -p "{root}"',
    )
    _patch_claude_home(monkeypatch, fake_claude, tmp_path)

    code = bridges_doctor_cmd(mem, tools=("claude",), console=None)
    assert code == 0
