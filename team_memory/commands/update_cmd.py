"""team-memory update — 原子更新一条记忆(刷新 updated, 自动校验)。

避免手工编辑 .md 破坏 frontmatter(团队场景下 merge 冲突易损坏结构)。
支持: --note 追加更新段 / --from-file 替换正文 / --supersede 标记废弃。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rich.console import Console

from ..models import MemoryStatus, MemoryValidationError, today_iso, validate_entry
from ..store import MemoryStore

__all__ = ["update_cmd"]


def update_cmd(
    memory_id: str,
    *,
    note: str | None = None,
    from_file: str | None = None,
    supersede: str | None = None,
    root: Path | None = None,
    console: Console | None = None,
) -> Path:
    """更新一条记忆; 返回写入路径。"""
    console = console or Console()
    store = MemoryStore.open(root)
    entry = store.get_entry(memory_id)
    if entry is None:
        raise ValueError(f"未找到记忆: {memory_id}")

    if supersede:
        if store.get_entry(supersede) is None:
            raise ValueError(f"supersede 目标不存在: {supersede}")
        new_entry = replace(
            entry,
            status=MemoryStatus.SUPERSEDED,
            superseded_by=supersede,
            updated=today_iso(),
        )
        action = f"标记为 superseded → {supersede}"
    elif from_file:
        new_body = Path(from_file).read_text(encoding="utf-8").strip()
        new_entry = replace(entry, body=new_body, updated=today_iso())
        action = "替换正文(--from-file)"
    elif note:
        stamp = today_iso()
        new_body = (
            entry.body.rstrip() + f"\n\n## 更新（{stamp}）\n\n{note.strip()}\n"
        )
        new_entry = replace(entry, body=new_body, updated=today_iso())
        action = f"追加更新段({stamp})"
    else:
        raise ValueError("需指定 --note / --from-file / --supersede 之一")

    errors = validate_entry(new_entry)
    if errors:
        raise MemoryValidationError("; ".join(errors))

    path = store.save_entry(new_entry)
    console.print(f"[green]✓[/] 已更新 [bold]{memory_id}[/] — {action}")
    console.print(f"  文件: {path}")
    console.print("[dim]  下一步: git add/commit; 新内容下个会话才加载[/]")
    return path
