"""Claude Code 桥接 — 全局 skill: ~/.claude/skills/team-memory/SKILL.md。"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import Config
from ..store import MemoryStore
from .common import build_skill_content, default_home, write_skill, report_skip

__all__ = ["bridge_claude", "CLAUDE_HOME"]

CLAUDE_HOME = default_home("claude")


def bridge_claude(
    store: MemoryStore,
    config: Config,
    *,
    home: Path | None = None,
    console: Console | None = None,
) -> Path | None:
    """注册 team-memory 为 Claude Code 全局 skill。"""
    console = console or Console()
    resolved = home or CLAUDE_HOME
    if not resolved.exists():
        report_skip("Claude Code", resolved, console)
        return None
    path = write_skill(resolved, "team-memory", build_skill_content(store, config))
    console.print(f"[green]✓ Claude Code[/] skill: {path}")
    return path
