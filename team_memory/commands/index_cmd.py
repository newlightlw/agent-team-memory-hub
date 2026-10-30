"""team-memory index — 生成各类型目录的 _index.md(按日期倒序)。

便于团队浏览: memory/{type}/_index.md 列出该类型所有记忆的 id/标题/作者/来源/状态。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..store import MemoryStore

__all__ = ["index_cmd"]


def index_cmd(
    root: Path | None = None,
    *,
    console: Console | None = None,
) -> list[Path]:
    """生成各类型 _index.md; 返回写入的文件列表。"""
    console = console or Console()
    store = MemoryStore.open(root)
    store.assert_writable()
    written: list[Path] = []

    from ..models import TYPE_DIR

    for type_key, dir_name in TYPE_DIR.items():
        entries = sorted(
            store.list_entries(type_key), key=lambda e: e.created, reverse=True
        )
        target_dir = store.memory_dir() / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "_index.md"

        if not entries:
            continue
        lines = [
            f"# {dir_name} 索引（{len(entries)} 条，按日期倒序）",
            "",
            "| ID | 标题 | 作者 | 来源 | 创建 | 状态 |",
            "|---|---|---|---|---|---|",
        ]
        for entry in entries:
            status = entry.status.value
            if entry.superseded_by:
                status = f"{status}→{entry.superseded_by}"
            title = entry.title.replace("|", "\\|")
            lines.append(
                f"| `{entry.id}` | {title} | {entry.author or '—'} | "
                f"{entry.source or '—'} | {entry.created} | {status} |"
            )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(target)

    for path in written:
        console.print(f"[green]✓[/] {path.relative_to(store.root)}")
    if not written:
        console.print("[yellow]暂无记忆, 未生成索引[/]")
    else:
        console.print(f"[bold green]已生成 {len(written)} 个索引文件[/]")
    return written
