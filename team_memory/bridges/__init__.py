"""工具桥接注册表 — 把 team-memory 注册到各 AI 工具。

全局模式: Claude/Hermes/Trae 装 skill(~/.*/skills/team-memory/SKILL.md),
Codex 配 AGENTS.md 标记段。
"""

from __future__ import annotations

from typing import Callable

from .claude import bridge_claude
from .codex import bridge_codex
from .common import default_home
from .hermes import bridge_hermes
from .trae import bridge_trae

BridgeFn = Callable[..., object]

# 工具 -> 全局桥接函数
GLOBAL_BRIDGES: dict[str, BridgeFn] = {
    "claude": bridge_claude,
    "codex": bridge_codex,
    "hermes": bridge_hermes,
    "trae": bridge_trae,
}

SUPPORTED_TOOLS: tuple[str, ...] = tuple(GLOBAL_BRIDGES.keys())


def is_tool_installed(tool: str) -> bool:
    """工具的全局配置目录是否存在。"""
    if tool not in GLOBAL_BRIDGES:
        return False
    return default_home(tool).exists()


__all__ = [
    "GLOBAL_BRIDGES",
    "SUPPORTED_TOOLS",
    "is_tool_installed",
    "bridge_claude",
    "bridge_codex",
    "bridge_hermes",
    "bridge_trae",
]
