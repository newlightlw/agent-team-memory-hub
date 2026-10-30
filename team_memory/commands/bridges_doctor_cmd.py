"""检查各 AI 工具桥接(skill)是否已正确安装。"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..bridges.common import TOOL_HOMES, default_home
from ..config import load_config
from ..store import MemoryStore

__all__ = ["bridges_doctor_cmd"]

_REQUIRED_SKILLS = ("team-memory", "auto-commit-memory")


def _skill_path(home: Path, name: str) -> Path:
    return home / "skills" / name / "SKILL.md"


def _read_settings_hooks(settings: Path) -> list[str]:
    """读取 Claude settings.json 里可能误配的 hooks 命令。"""
    if not settings.exists():
        return []
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    hooks = data.get("hooks", {})
    commands: list[str] = []
    if isinstance(hooks, dict):
        for entries in hooks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("command"):
                    commands.append(str(entry["command"]))
    return commands


def bridges_doctor_cmd(
    root: Path | None = None,
    *,
    tools: tuple[str, ...] = ("claude", "codex", "hermes", "trae"),
    console: Console | None = None,
) -> int:
    """检查全局 skill 安装; 返回问题数(0=健康)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    config = load_config(store.root / ".env")
    expected_root = str(store.root)
    problems = 0

    console.print("[bold]检查 AI 工具桥接(skill)[/]")
    console.print(f"  记忆仓库: [cyan]{expected_root}[/]")

    for tool in tools:
        if tool not in TOOL_HOMES:
            console.print(f"[yellow]⚠ 未知工具 {tool!r}, 跳过[/]")
            continue
        home = default_home(tool)
        if not home.exists():
            console.print(
                f"[dim]○ {tool}[/]: 未安装({home} 不存在), 跳过"
            )
            continue

        for skill_name in _REQUIRED_SKILLS:
            path = _skill_path(home, skill_name)
            if not path.exists():
                console.print(f"[red]✗ {tool}[/]: 缺少 skill {path}")
                problems += 1
                continue
            text = path.read_text(encoding="utf-8")
            if skill_name == "auto-commit-memory":
                if expected_root not in text:
                    console.print(
                        f"[red]✗ {tool}[/]: auto-commit skill 未嵌入记忆路径 {expected_root}\n"
                        f"    请运行: python -m team_memory load --global --tools {tool} "
                        f"-p {expected_root}"
                    )
                    problems += 1
                elif "team_memory save" not in text and "team-memory save" not in text:
                    console.print(
                        f"[yellow]⚠ {tool}[/]: auto-commit skill 版本过旧(未使用 save 命令), "
                        "请 git pull 工具仓库后重新 load --global"
                    )
                    problems += 1
                else:
                    console.print(f"[green]✓ {tool}[/]: {skill_name} 已安装且路径正确")
            else:
                console.print(f"[green]✓ {tool}[/]: {skill_name} 已安装")

    if "claude" in tools:
        settings = default_home("claude") / "settings.json"
        hook_cmds = _read_settings_hooks(settings)
        bad = [c for c in hook_cmds if "team-memory" in c or "team_memory" in c]
        if bad:
            console.print(
                "[red]✗ Claude Code[/]: 检测到 settings.json 里配置了 team-memory hooks, "
                "这与本项目冲突:\n"
                + "\n".join(f"    - {c}" for c in bad)
                + "\n    请删除 hooks, 改用 ~/.claude/skills/auto-commit-memory/SKILL.md"
            )
            problems += 1
        elif settings.exists():
            console.print("[green]✓ Claude Code[/]: settings.json 无冲突 hooks")

    if problems == 0:
        console.print(
            "\n[green]✓ 桥接健康[/] — 说「提交一下/存一下/沉淀一下」前请[bold]新开 Claude Code 会话[/]"
        )
    else:
        console.print(
            f"\n[yellow]共 {problems} 个问题[/] — 修复后新开 Claude Code 会话再试"
        )
    return problems
