"""team-memory load — 把团队记忆加载到工具。

两种模式:
  --global       : 注册到各工具全局(Claude/Hermes/Trae skill + Codex AGENTS.md)。
                   一次配好, 所有项目所有工具自动可用。
  默认(项目级)   : 在 target 项目生成桥接文件(CLAUDE.md / AGENTS.md / .trae/rules)。
                   Hermes 无项目级概念, 只能 --global。
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from ..bridges import GLOBAL_BRIDGES
from ..bridges.common import (
    build_agents_section,
    build_listing,
    install_aux_skills,
    update_marked_section,
)
from ..config import Config, load_config
from ..sources import load_all_entries
from ..store import MemoryStore
from ..templating import render

__all__ = ["load_cmd", "SUPPORTED_TOOLS"]

SUPPORTED_TOOLS = ("claude", "codex", "hermes", "trae")

_PROJECT_CLAUDE_TEMPLATE = """\
# {project} — Agent 工作说明

本项目接入 **{team_name}** 团队记忆系统。

## 团队记忆位置

`{root}`

> 若通过 `--link` 创建了软链, 也可用相对路径 `.memory/` 访问。

## 启动时优先阅读

- 团队指令: `{root}/CLAUDE.md`
- 团队规范: `{root}/rules/`
- 项目记忆: `{root}/memory/project/`
- 决策(ADR): `{root}/memory/decisions/`
- 错误记忆: `{root}/memory/errors/`
- Skill: `{root}/memory/skills/`

## 工作规则

1. 不要绕过团队记忆中的架构约束
2. 发现代码与记忆冲突时, 先指出冲突, 不直接修改
3. 产生新决策 -> 用 `team-memory capture "标题" -t decision -p {root}` 沉淀
4. 解决非平凡错误 -> 用 `team-memory capture "标题" -t error -p {root}` 沉淀
5. 新写入的记忆在下一个会话才生效(避免污染当前对话)

## 当前可用记忆(共 {count} 条)

{listing}
"""


def load_cmd(
    target: Path | None = None,
    tools: tuple[str, ...] = ("claude",),
    *,
    root: Path | None = None,
    link: bool = False,
    global_mode: bool = False,
    aux_skill: bool = True,
    console: Console | None = None,
) -> list[Path]:
    """加载团队记忆到工具; 返回生成的文件路径列表。"""
    console = console or Console()
    store = MemoryStore.open(root)
    config = load_config(env_path=store.root / ".env")
    written: list[Path] = []

    if global_mode:
        for tool in tools:
            bridge = GLOBAL_BRIDGES.get(tool)
            if bridge is None:
                console.print(
                    f"[yellow]{tool!r}: 未知工具, 可选 "
                    f"{list(GLOBAL_BRIDGES)}[/]"
                )
                continue
            path = bridge(store, config, console=console)
            if path is not None:
                written.append(path)
        if aux_skill:
            install_aux_skills(tools, store, config, console)
        return written

    # 项目级
    if target is None:
        raise ValueError("项目级 load 需要指定 target 路径(或使用 --global)")
    target_path = Path(target).resolve()
    target_path.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        if tool == "claude":
            written.append(
                _generate_project_claude(store, target_path, config, link, console)
            )
        elif tool == "codex":
            written.append(_generate_project_agents(store, target_path, config, console))
        elif tool == "trae":
            written.append(_generate_project_trae(store, target_path, config, console))
        else:
            console.print(
                f"[yellow]{tool!r}: 项目级未实现(Hermes 只能 --global)[/]"
            )
    return written


def _entry_count(store: MemoryStore, config: Config) -> int:
    grouped = load_all_entries(config, store.root)
    return sum(len(lst) for lst in grouped.values())


def _generate_project_claude(
    store: MemoryStore, target: Path, config: Config, link: bool, console: Console
) -> Path:
    content = render(
        _PROJECT_CLAUDE_TEMPLATE,
        project=target.name,
        team_name=config.team_name,
        root=str(store.root),
        count=str(_entry_count(store, config)),
        listing=build_listing(config, store.root),
    )
    path = target / "CLAUDE.md"
    path.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ Claude Code[/] 项目桥接: {path}")
    if link:
        _try_link(store.root, target / ".memory", console)
    return path


def _generate_project_agents(
    store: MemoryStore, target: Path, config: Config, console: Console
) -> Path:
    path = update_marked_section(
        target / "AGENTS.md", build_agents_section(store, config)
    )
    console.print(f"[green]✓ Codex[/] 项目 AGENTS.md: {path}")
    return path


def _generate_project_trae(
    store: MemoryStore, target: Path, config: Config, console: Console
) -> Path:
    rules_dir = target / ".trae" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / "team-memory.md"
    path.write_text(build_agents_section(store, config), encoding="utf-8")
    console.print(f"[green]✓ Trae[/] 项目规则: {path}")
    return path


def _try_link(src: Path, link_path: Path, console: Console) -> None:
    try:
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        os.symlink(src, link_path)
        console.print(f"[green]✓[/] 创建软链: {link_path} -> {src}")
    except OSError as exc:
        hint = "mklink" if os.name == "nt" else "ln -s"
        console.print(
            f"[yellow]⚠ 创建软链失败({exc}); 可手动: "
            f"{hint} {src} {link_path} "
            f"(Windows 需管理员/开发者模式, 或不用 --link)[/]"
        )
