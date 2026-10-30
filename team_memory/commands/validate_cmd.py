"""team-memory validate — 批量校验记忆仓库(供 CI 和人工巡检)。

校验: 解析失败文件 / 必填字段(validate_entry) / id 唯一性 / 引用有效性。
退出码: 有 error → 1(CI 阻断); --strict 时 warning 也算失败。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..models import validate_entry
from ..store import MemoryStore

__all__ = ["validate_cmd"]


def validate_cmd(
    root: Path | None = None,
    *,
    strict: bool = False,
    console: Console | None = None,
) -> int:
    """校验整个仓库; 返回 0(通过)/1(失败)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    errors = 0
    warnings = 0

    # 1. 解析失败文件
    for path, err in store.list_parse_errors():
        console.print(
            f"[red]✗ {path.relative_to(store.root)}: frontmatter 解析失败 — {err}[/]"
        )
        errors += 1

    entries = store.list_entries()

    # 2. 必填字段 + id 格式
    for entry in entries:
        for err in validate_entry(entry):
            console.print(f"[red]✗ {entry.id}: {err}[/]")
            errors += 1

    # 3. id 唯一性
    for mid, paths in store.check_unique().items():
        console.print(
            f"[red]✗ 重复 id {mid}: {[p.relative_to(store.root) for p in paths]}[/]"
        )
        errors += 1

    # 4. 引用有效性(警告, 不 fail)
    all_ids = {e.id for e in entries}
    for entry in entries:
        for ref in entry.related:
            if ref not in all_ids:
                console.print(f"[yellow]⚠ {entry.id}.related → {ref} (悬空)[/]")
                warnings += 1
        if entry.superseded_by and entry.superseded_by not in all_ids:
            console.print(
                f"[yellow]⚠ {entry.id}.superseded_by → {entry.superseded_by} (悬空)[/]"
            )
            warnings += 1

    total = len(entries)
    if errors == 0 and warnings == 0:
        console.print(f"[green]✓ 校验通过: {total} 条记忆, 0 错误 0 警告[/]")
    else:
        color = "red" if errors else "yellow"
        console.print(
            f"\n[{color}]校验完成: {total} 条, {errors} 错误, {warnings} 警告[/]"
        )

    failed = errors + (warnings if strict else 0)
    return 1 if failed else 0
