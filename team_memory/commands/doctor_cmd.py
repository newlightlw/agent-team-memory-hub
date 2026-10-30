"""team-memory doctor — 诊断记忆仓库健康(供人工巡检)。

检查: 解析失败文件 / 重复 id / 必填字段 / 悬空 related / 悬空 superseded_by / 缺 author。
退出码 = 是否有问题(0 = 健康)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.console import Console

from ..models import validate_entry
from ..store import MemoryStore

__all__ = ["doctor_cmd"]


def doctor_cmd(
    root: Path | None = None,
    *,
    console: Console | None = None,
) -> int:
    """诊断仓库健康; 返回问题数(0 = 健康)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    problems = 0

    # 1. 解析失败文件(不再静默)
    for path, err in store.list_parse_errors():
        console.print(
            f"[red]✗ 解析失败: {path.relative_to(store.root)} — {err}[/]"
        )
        problems += 1

    entries = store.list_entries()

    # 2. 重复 id
    for mid, paths in store.check_unique().items():
        console.print(
            f"[red]✗ 重复 id {mid}: {[p.relative_to(store.root) for p in paths]}[/]"
        )
        problems += 1

    # 3. 必填字段校验
    for entry in entries:
        for err in validate_entry(entry):
            console.print(f"[red]✗ {entry.id}: {err}[/]")
            problems += 1

    # 4. 引用有效性
    all_ids = {e.id for e in entries}
    for entry in entries:
        for ref in entry.related:
            if ref not in all_ids:
                console.print(f"[yellow]⚠ {entry.id}.related → {ref} (悬空)[/]")
                problems += 1
        if entry.superseded_by and entry.superseded_by not in all_ids:
            console.print(
                f"[yellow]⚠ {entry.id}.superseded_by → {entry.superseded_by} (悬空)[/]"
            )
            problems += 1

    # 5. author 缺失
    for entry in entries:
        if not entry.author:
            console.print(f"[yellow]⚠ {entry.id} 缺 author(无法追溯沉淀者)[/]")
            problems += 1

    # 6. 过期检查(expires < today)
    today_str = date.today().isoformat()
    for entry in entries:
        if entry.expires and entry.expires < today_str:
            console.print(
                f"[yellow]⚠ {entry.id} 已过期(expires={entry.expires}), 需复查或废弃[/]"
            )
            problems += 1

    if problems == 0:
        console.print(f"[green]✓ 仓库健康: {len(entries)} 条记忆, 无问题[/]")
    else:
        console.print(f"\n[yellow]共 {problems} 个问题(详见上方)[/]")
    return 1 if problems else 0
