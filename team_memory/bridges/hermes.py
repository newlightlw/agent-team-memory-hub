"""Hermes 桥接 — 全局 skill: ~/.hermes/skills/team-memory/SKILL.md。

Hermes 是全局 agent, 无项目级概念, 必须走全局 skill。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import Config
from ..store import MemoryStore
from .common import build_skill_content, default_home, write_skill, report_skip

__all__ = ["bridge_hermes", "HERMES_HOME"]

HERMES_HOME = default_home("hermes")


def bridge_hermes(
    store: MemoryStore,
    config: Config,
    *,
    home: Path | None = None,
    console: Console | None = None,
) -> Path | None:
    """注册 team-memory 为 Hermes 全局 skill。"""
    console = console or Console()
    resolved = home or HERMES_HOME
    if not resolved.exists():
        report_skip("Hermes", resolved, console)
        return None
    path = write_skill(resolved, "team-memory", build_skill_content(store, config))
    console.print(f"[green]✓ Hermes[/] skill: {path}")
    return path
