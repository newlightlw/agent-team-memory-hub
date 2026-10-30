"""team-memory inbox 候选记忆 — AI/未验证经验先进 inbox, 人工 approve 后转正式。

对应 Gateway 方案的核心: AI 可提交 candidate, 但不能直接写正式记忆。
  propose: 写 candidate 到 inbox/(status=pending_review)
  review:  列待审 candidate
  approve: candidate → 正式记忆(memory/{type}/, status=active)
  decline: candidate 标 declined(留 inbox 供追溯)
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..gitutil import get_git_config
from ..models import (
    MemoryEntry,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryValidationError,
    author_slug,
    today_iso,
    validate_entry,
)
from ..store import MemoryStore
from .capture_cmd import _build_body

__all__ = ["propose_cmd", "review_cmd", "approve_cmd", "decline_cmd"]


def propose_cmd(
    title: str,
    type: str,
    *,
    scope: str = "team",
    author: str = "",
    source: str = "",
    role: str = "",
    tags: tuple[str, ...] = (),
    related: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    confidence: str = "medium",
    note: str = "",
    from_file: str | None = None,
    root: Path | None = None,
    console: Console | None = None,
) -> Path:
    """提交候选记忆到 inbox(pending_review)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    try:
        type_enum = MemoryType(type)
        scope_enum = MemoryScope(scope)
    except ValueError as exc:
        raise ValueError(f"类型/scope 非法: {exc}") from exc

    if not author:
        cfg = load_config(env_path=store.root / ".env")
        author = cfg.default_author or author_slug(get_git_config("user.name"))

    entry_id = store.next_id(author=author)
    body = _build_body(type_enum, title, note, from_file)
    entry = MemoryEntry(
        id=entry_id,
        type=type_enum,
        title=title,
        scope=scope_enum,
        author=author,
        source=source,
        role=role,
        created=today_iso(),
        updated=today_iso(),
        status=MemoryStatus.PENDING_REVIEW,
        confidence=confidence,
        tags=tuple(tags),
        related=tuple(related),
        evidence=tuple(evidence),
        body=body,
    )
    errors = validate_entry(entry)
    if errors:
        raise MemoryValidationError("; ".join(errors))
    path = store.propose_entry(entry)
    console.print(
        f"[green]✓[/] 已提交候选 [bold]{entry_id}[/] "
        f"(pending_review, confidence={confidence})"
    )
    console.print(f"  文件: {path}")
    console.print(
        f"  [dim]待审核: team-memory review → team-memory approve {entry_id}[/]"
    )
    return path


def review_cmd(
    root: Path | None = None,
    *,
    status: str = "pending_review",
    console: Console | None = None,
) -> None:
    """列出 inbox 候选记忆。"""
    console = console or Console()
    store = MemoryStore.open(root)
    entries = store.list_inbox(status_filter=None if status == "all" else status)
    if not entries:
        console.print(f"[yellow]inbox 无 {status} 候选记忆[/]")
        return
    table = Table(title=f"inbox 候选 · {len(entries)} 条 (status={status})")
    for col in ("ID", "类型", "标题", "来源", "置信度", "作者", "创建"):
        table.add_column(col)
    for entry in sorted(entries, key=lambda e: e.created, reverse=True):
        table.add_row(
            entry.id, entry.type.value, entry.title[:32],
            entry.source or "—", entry.confidence or "—",
            entry.author or "—", entry.created,
        )
    console.print(table)
    console.print(
        "[dim]审核: team-memory approve <id> 或 team-memory decline <id>[/]"
    )


def approve_cmd(
    memory_id: str,
    root: Path | None = None,
    *,
    console: Console | None = None,
) -> Path:
    """通过候选 → 转正式记忆。"""
    console = console or Console()
    store = MemoryStore.open(root)
    path = store.approve_entry(memory_id)
    console.print(f"[green]✓[/] 已通过 [bold]{memory_id}[/] → 正式记忆: {path}")
    console.print("[dim]  下一步: git add/commit; 新内容下个会话才加载[/]")
    return path


def decline_cmd(
    memory_id: str,
    root: Path | None = None,
    *,
    reason: str = "",
    console: Console | None = None,
) -> Path:
    """拒绝候选(标 declined, 留 inbox 供追溯)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    path = store.decline_entry(memory_id)
    console.print(
        f"[yellow]✓[/] 已拒绝 [bold]{memory_id}[/] (declined)"
        + (f" — {reason}" if reason else "")
    )
    return path
