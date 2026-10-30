"""team-memory list / show — 可视化记忆: 来源 / 入库时间 / 版本。

list: 表格列出所有记忆(含来源工具、创建/更新时间、git 版本摘要)。
show: 单条记忆详情 + 该文件的 git 版本历史(commit 列表) + 关联记忆。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..gitutil import run_git
from ..store import MemoryStore

__all__ = ["list_cmd", "show_cmd"]


def _file_version(repo_root: Path, path: Path | None) -> str:
    """返回文件的版本摘要: 'vN (最新hash)'; 未提交返回'未提交'。"""
    if path is None:
        return "—"
    rel = path.relative_to(repo_root)
    result = run_git(repo_root, "log", "--oneline", "--", str(rel))
    if result.returncode != 0:
        return "未跟踪"
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        return "未提交"
    short = lines[0].split()[0]
    return f"v{len(lines)} ({short})"


def list_cmd(
    root: Path | None = None,
    *,
    type_filter: str | None = None,
    console: Console | None = None,
) -> None:
    """以表格列出所有记忆。"""
    console = console or Console()
    store = MemoryStore.open(root)
    entries = store.list_entries(type_filter)
    if not entries:
        console.print("[yellow]暂无记忆。用 team-memory capture 沉淀。[/]")
        return

    table = Table(title=f"团队记忆 · 共 {len(entries)} 条", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("类型", style="magenta")
    table.add_column("标题")
    table.add_column("作者", style="green")
    table.add_column("来源", style="yellow")
    table.add_column("创建", style="dim")
    table.add_column("更新", style="dim")
    table.add_column("版本", style="blue")

    # 按创建时间倒序(新的在前)
    for entry in sorted(entries, key=lambda e: e.created, reverse=True):
        path = store.find_file(entry.id)
        table.add_row(
            entry.id,
            entry.type.value,
            entry.title[:40],
            entry.author or "—",
            entry.source or "—",
            entry.created or "—",
            entry.updated or "—",
            _file_version(store.root, path),
        )
    console.print(table)


def show_cmd(
    memory_id: str,
    root: Path | None = None,
    *,
    console: Console | None = None,
) -> None:
    """查看单条记忆详情 + git 版本历史。"""
    console = console or Console()
    store = MemoryStore.open(root)
    entry = store.get_entry(memory_id)
    if entry is None:
        raise ValueError(f"未找到记忆: {memory_id}")
    path = store.find_file(memory_id)

    console.print(f"[bold cyan]记忆 {entry.id}[/]")
    console.print(
        f"  类型: {entry.type.value}   范围: {entry.scope.value}   "
        f"状态: {entry.status.value}"
    )
    console.print(
        f"  作者: {entry.author or '—'}   来源: {entry.source or '—'}"
    )
    console.print(f"  创建: {entry.created}   更新: {entry.updated}")
    if entry.tags:
        console.print(f"  标签: {', '.join(entry.tags)}")
    if entry.related:
        console.print(f"  关联: {', '.join(entry.related)}")
    if entry.superseded_by:
        console.print(f"  [yellow]已被取代 → {entry.superseded_by}[/]")

    console.print("\n[bold]正文[/]")
    console.print(entry.body)

    if path is not None:
        rel = path.relative_to(store.root)
        result = run_git(
            store.root, "log", "--pretty=%h | %ad | %s",
            "--date=short", "--", str(rel),
        )
        console.print(f"\n[bold]版本历史[/] ({rel})")
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                console.print(f"  {line}")
        else:
            console.print("  [dim]未提交(尚无 git 历史)[/]")
