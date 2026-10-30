"""Trae 桥接 — 全局 skill: ~/.trae/skills/team-memory/SKILL.md。

Trae 是 VS Code fork, 有 skills 体系(~/.trae/skills/), 与 Claude/Hermes 同构。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import Config
from ..store import MemoryStore
from .common import build_skill_content, default_home, write_skill, report_skip

__all__ = ["bridge_trae", "TRAE_HOME"]

TRAE_HOME = default_home("trae")


def bridge_trae(
    store: MemoryStore,
    config: Config,
    *,
    home: Path | None = None,
    console: Console | None = None,
) -> Path | None:
    """注册 team-memory 为 Trae 全局 skill。"""
    console = console or Console()
    resolved = home or TRAE_HOME
    if not resolved.exists():
        report_skip("Trae", resolved, console)
        return None
    path = write_skill(resolved, "team-memory", build_skill_content(store, config))
    console.print(f"[green]✓ Trae[/] skill: {path}")
    return path
