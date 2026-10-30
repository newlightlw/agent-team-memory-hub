"""工具桥接共用逻辑 — skill / AGENTS 内容生成 + 幂等写入。

Claude / Hermes / Trae 都用 skill 机制(~/.*/skills/team-memory/SKILL.md);
Codex 用 AGENTS.md 的标记段(幂等更新, 不破坏用户已有内容)。
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from ..config import Config
from ..sources import load_all_entries
from ..store import MemoryStore
from ..templating import TEMPLATES_DIR, render

__all__ = [
    "TOOL_HOMES",
    "MARKER_START",
    "MARKER_END",
    "default_home",
    "build_listing",
    "build_skill_content",
    "build_agents_section",
    "write_skill",
    "update_marked_section",
    "install_aux_skills",
]

# 各工具的全局配置根目录
TOOL_HOMES: dict[str, str] = {
    "claude": "~/.claude",
    "codex": "~/.codex",
    "hermes": "~/.hermes",
    "trae": "~/.trae",
}

MARKER_START = "<!-- team-memory:start -->"
MARKER_END = "<!-- team-memory:end -->"


def default_home(tool: str) -> Path:
    """返回工具的全局配置根(~/.claude 等)。"""
    return Path(TOOL_HOMES[tool]).expanduser()


def build_listing(config: Config, team_root: Path) -> str:
    """聚合所有源的记忆, 生成可读清单。"""
    grouped = load_all_entries(config, team_root)
    entries = [entry for lst in grouped.values() for entry in lst]
    if not entries:
        return "(暂无记忆, 用 team-memory capture 沉淀)"
    lines: list[str] = []
    for source_name, lst in grouped.items():
        lines.append(f"### 源: {source_name} ({len(lst)} 条)")
        for entry in lst:
            tags = f" `{','.join(entry.tags)}`" if entry.tags else ""
            lines.append(f"- `{entry.id}` {entry.title}{tags}")
        lines.append("")
    return "\n".join(lines).strip()


_SKILL_TEMPLATE = """\
---
name: team-memory
description: |
  {team_name} 团队的共享记忆系统(Git 管理)。读取团队的项目记忆、决策(ADR)、
  错误解决方案、已验证 Skill 流程; 用 `team-memory capture` 沉淀新经验。
  何时用: 在本团队项目工作、需要团队上下文、做技术决策前、遇到错误时、
  或解决非平凡问题后想沉淀经验时, 主动使用。
  记忆仓库: {root}
---

# Team Memory — {team_name}

> 团队认知的压缩包, 不是聊天记录。Git 管理, 可版本/可审核/可回滚。

## 记忆仓库

`{root}`

## 五类记忆速查

| 类型 | 路径 | 何时读 | 何时写 |
|------|------|--------|--------|
| 项目 | memory/project/ | 接手任务时 | 项目范围变化时 |
| 代码 | memory/code/ | 写代码前 | 发现重要结构时 |
| 决策 | memory/decisions/ | 做技术选择前 | 做出重要决策后 |
| 错误 | memory/errors/ | 遇到错误时 | 解决非平凡错误后 |
| Skill | memory/skills/ | 执行流程前 | 验证可复用流程后 |

## 沉淀新记忆

```bash
team-memory capture "标题" -t decision -p "{root}"   # 决策(ADR)
team-memory capture "标题" -t error -p "{root}"      # 错误解决方案
team-memory capture "标题" -t skill -p "{root}"      # 可复用流程
team-memory capture "标题" -t project -p "{root}"    # 项目记忆
```

## 规则

1. **新写入下个会话才生效** — 不在当前对话依赖刚写入的记忆
2. **不自动覆盖核心记忆** — project/decisions 只建议, 走人工审核
3. **废弃不删除** — status=superseded + superseded_by 链接到新记忆
4. **secrets 不入库** — .env / token 已 gitignore

## 当前可用记忆(共 {count} 条)

{listing}
"""


def build_skill_content(store: MemoryStore, config: Config) -> str:
    """生成 SKILL.md 全文(Claude/Hermes/Trae 共用)。"""
    grouped = load_all_entries(config, store.root)
    count = sum(len(lst) for lst in grouped.values())
    return render(
        _SKILL_TEMPLATE,
        team_name=config.team_name,
        root=str(store.root),
        count=str(count),
        listing=build_listing(config, store.root),
    )


_AGENTS_SECTION = """\
## Team Memory — {team_name}

团队共享记忆系统(Git 管理)。仓库: `{root}`

- 读取: memory/project/(项目) memory/decisions/(决策) memory/errors/(错误) memory/skills/(流程)
- 沉淀: `team-memory capture "标题" -t <decision|error|skill|project> -p "{root}"`
- 规则: 新写入下个会话生效; 不自动覆盖核心记忆; 废弃不删除; secrets 不入库
- 当前可用记忆: {count} 条
"""


def build_agents_section(store: MemoryStore, config: Config) -> str:
    """生成 Codex AGENTS.md 的 team-memory 段(不含 marker)。"""
    grouped = load_all_entries(config, store.root)
    count = sum(len(lst) for lst in grouped.values())
    return render(
        _AGENTS_SECTION,
        team_name=config.team_name,
        root=str(store.root),
        count=str(count),
    )


def write_skill(home: Path, skill_name: str, content: str) -> Path:
    """写入 home/skills/skill_name/SKILL.md(总是覆盖, 内容由仓库动态生成)。"""
    skill_dir = home / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def update_marked_section(
    path: Path,
    section: str,
    *,
    start: str = MARKER_START,
    end: str = MARKER_END,
) -> Path:
    """幂等更新文件中 marker 包裹的段(已有则替换, 无则追加)。

    保留 marker 外的用户原有内容。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{start}\n{section.strip()}\n{end}"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(existing):
        updated = pattern.sub(lambda _: block, existing)
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
    else:
        updated = block + "\n"
    path.write_text(updated, encoding="utf-8")
    return path


def report_skip(tool: str, home: Path, console: Console) -> None:
    console.print(
        f"[yellow]⚠ {tool}: 未检测到 {home} (工具未安装/未配置), 跳过[/]"
    )


def install_aux_skills(
    tools,
    store: MemoryStore,
    config: Config,
    console: Console,
) -> list[Path]:
    """把 auto-commit-memory skill 装到各工具(随 load --global 分发, 嵌入记忆仓库路径)。"""
    aux = TEMPLATES_DIR / "skills" / "auto-commit-memory" / "SKILL.md"
    if not aux.exists():
        console.print("[dim]未找到 auto-commit-memory 模板, 跳过辅助 skill[/]")
        return []
    import sys

    memory_remote = config.gitea_remote_url or f"(请配置 {store.root}/.env 的 GITEA_REMOTE_URL)"
    web_url = config.web_public_url or "(见 .env 的 WEB_PUBLIC_URL)"
    content = render(
        aux.read_text(encoding="utf-8"),
        root=str(store.root),
        author=config.default_author or "<你的英文短名>",
        python=sys.executable,
        memory_remote=memory_remote,
        web_url=web_url,
    )
    written: list[Path] = []
    for tool in tools:
        home = default_home(tool)
        if not home.exists():
            continue
        path = write_skill(home, "auto-commit-memory", content)
        console.print(f"[green]✓ {tool}[/] auto-commit skill: {path}")
        written.append(path)
    return written
