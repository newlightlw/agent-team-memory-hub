"""team-memory save — 沉淀记忆 + git commit(供「提交一下」一键闭环)。

在**记忆数据仓库**内原子执行 capture → git add → git commit,
避免 AI 误在 agent-team-memory 工具仓库手写 md 或 commit 错仓库。
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from ..gitutil import GitError, is_git_repo, run_git
from ..repo_guard import resolve_memory_root
from .capture_cmd import capture_cmd
from .sync_cmd import sync_cmd

__all__ = ["save_cmd"]


def save_cmd(
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
    do_sync: bool = False,
    console: Console | None = None,
) -> Path:
    """沉淀一条记忆并在记忆仓库内 commit; 可选 sync 推送到 Git 远端。"""
    console = console or Console()
    mem_root = resolve_memory_root(root)
    path = capture_cmd(
        title,
        type,
        scope=scope,
        author=author,
        source=source,
        role=role,
        tags=tags,
        related=related,
        note=note,
        from_file=from_file,
        root=mem_root,
        console=console,
    )

    if not is_git_repo(mem_root):
        console.print(
            "[yellow]⚠[/] 记忆仓库未初始化 git, 已写入文件但未 commit。"
            "请在该目录运行 git init 或 team-memory init。"
        )
        return path

    rel = path.relative_to(mem_root)
    add_result = run_git(mem_root, "add", str(rel))
    if add_result.returncode != 0:
        raise GitError(add_result.stderr.strip() or "git add 失败")

    via_suffix = f" [via {source}]" if source else ""
    commit_msg = f"memory({type}): {title}{via_suffix}"
    commit_result = run_git(mem_root, "commit", "-m", commit_msg)
    if commit_result.returncode != 0:
        stderr = commit_result.stderr.strip()
        if "nothing to commit" in stderr.lower():
            console.print("[yellow]⚠[/] 文件已存在且无变更, 跳过 commit。")
        else:
            raise GitError(stderr or "git commit 失败")
    else:
        console.print(f"[green]✓[/] 已 commit: {commit_msg}")

    console.print(f"[dim]记忆仓库: {mem_root}[/]")
    console.print(f"[dim]数据仓库 remote 应为 team-memory, 不是 agent-team-memory[/]")

    if do_sync:
        sync_cmd(mem_root, console=console)
    else:
        console.print(
            "[dim]如需同步团队, 运行: "
            f"{sys.executable} -m team_memory sync -p {mem_root}[/]"
        )
    return path
