"""team-memory capture — 沉淀一条记忆。

自动生成 id(mem-YYYYMMDD-NNN)、frontmatter, 套用类型模板, 落盘到 memory/{type}/。
不自动 commit(符合"人工审核"原则) — 写入后提示用户 git add/commit,
且按记忆模型约定, 新写入下个会话才生效。
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ..config import load_config
from ..gitutil import get_git_config
from ..models import (
    MemoryEntry,
    MemoryScope,
    MemoryType,
    MemoryValidationError,
    author_slug,
    today_iso,
    validate_entry,
)
from ..repo_guard import assert_valid_memory_repo
from ..store import MemoryStore
from ..templating import TEMPLATES_DIR, render

__all__ = ["capture_cmd"]


def capture_cmd(
    title: str,
    type: str,
    *,
    scope: str = "team",
    author: str = "",
    source: str = "",
    role: str = "",
    tags: tuple[str, ...] = (),
    related: tuple[str, ...] = (),
    note: str = "",
    from_file: str | None = None,
    root: Path | None = None,
    console: Console | None = None,
) -> Path:
    """沉淀一条记忆; 返回写入的文件路径。"""
    console = console or Console()
    store = MemoryStore.open(root)
    assert_valid_memory_repo(store.root)

    try:
        type_enum = MemoryType(type)
    except ValueError as exc:
        raise ValueError(
            f"未知记忆类型 {type!r}, 可选: "
            + ", ".join(t.value for t in MemoryType)
        ) from exc
    try:
        scope_enum = MemoryScope(scope)
    except ValueError as exc:
        raise ValueError(
            f"未知 scope {scope!r}, 可选: "
            + ", ".join(s.value for s in MemoryScope)
        ) from exc

    if not author:
        # .env 的 DEFAULT_AUTHOR → 否则 git config user.name 的 ascii slug
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
        tags=tuple(tags),
        related=tuple(related),
        body=body,
    )

    errors = validate_entry(entry)
    if errors:
        raise MemoryValidationError("; ".join(errors))

    path = store.save_entry(entry)
    console.print(
        f"[green]✓[/] 已沉淀记忆 [bold]{entry_id}[/] "
        f"(type={type_enum.value}, scope={scope_enum.value})"
    )
    console.print(f"  文件: {path}")
    console.print(
        "[dim]下一步: 编辑补全内容, 然后 git add/commit。"
        "按约定, 新写入的记忆在下一个会话才加载。[/]"
    )
    return path


def _build_body(
    type_enum: MemoryType,
    title: str,
    note: str,
    from_file: str | None,
) -> str:
    """构造记忆正文: 优先 from_file > note > 类型模板。"""
    if from_file:
        return Path(from_file).read_text(encoding="utf-8").strip()
    if note.strip():
        return f"# {title}\n\n{note.strip()}\n"
    template = TEMPLATES_DIR / "types" / f"{type_enum.value}.md"
    return render(template.read_text(encoding="utf-8"), title=title)
