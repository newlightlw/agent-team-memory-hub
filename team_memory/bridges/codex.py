"""Codex 桥接 — 全局指令: ~/.codex/AGENTS.md 的 team-memory 标记段。

用 marker 幂等更新, 不破坏用户在 AGENTS.md 里的其他内容。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import Config
from ..store import MemoryStore
from .common import (
    build_agents_section,
    default_home,
    report_skip,
    update_marked_section,
)

__all__ = ["bridge_codex", "CODEX_HOME"]

CODEX_HOME = default_home("codex")


def bridge_codex(
    store: MemoryStore,
    config: Config,
    *,
    home: Path | None = None,
    console: Console | None = None,
) -> Path | None:
    """在 Codex 全局 AGENTS.md 写入/更新 team-memory 段。"""
    console = console or Console()
    resolved = home or CODEX_HOME
    if not resolved.exists():
        report_skip("Codex", resolved, console)
        return None
    agents_md = resolved / "AGENTS.md"
    path = update_marked_section(agents_md, build_agents_section(store, config))
    console.print(f"[green]✓ Codex[/] AGENTS.md: {path}")
    return path
