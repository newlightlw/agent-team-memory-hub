"""Git 操作辅助(subprocess 封装)。

不依赖 GitPython, 直接调用系统 git, 减少 dependency。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = [
    "GitError",
    "run_git",
    "is_git_repo",
    "git_init",
    "get_git_config",
    "ensure_git_identity",
    "has_remote",
    "get_remote_url",
    "add_remote",
    "working_tree_dirty",
    "conflicted_files",
    "is_rebase_in_progress",
]


class GitError(RuntimeError):
    """git 命令执行失败。"""


def run_git(cwd: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """运行 git 命令, 捕获 stdout/stderr。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        timeout=30,
    )


def is_git_repo(path: Path) -> bool:
    """path 本身是否是 git 仓库根(存在 .git 目录或文件)。

    注意: 不能用 `git rev-parse --is-inside-work-tree`, 因为那会在
    path 位于某个父 git 工作树内时也返回 true, 导致 init 误判已初始化、
    跳过创建独立 .git(子仓库会被父仓库的 .gitignore 吞掉)。
    """
    return (path / ".git").exists()


def git_init(path: Path) -> bool:
    """初始化 git 仓库; 已是仓库则返回 False(未改动)。"""
    if is_git_repo(path):
        return False
    result = run_git(path, "init")
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git init 失败")
    return True


def get_git_config(key: str) -> str:
    """读取全局 git 配置项; 无则空串。"""
    result = run_git(Path.cwd(), "config", "--global", key)
    return result.stdout.strip() if result.returncode == 0 else ""


def ensure_git_identity() -> tuple[str, str]:
    """返回全局 (user.name, user.email); 未配置则为空串。"""
    return get_git_config("user.name"), get_git_config("user.email")


def has_remote(path: Path, name: str = "origin") -> bool:
    result = run_git(path, "remote")
    if result.returncode != 0:
        return False
    return name in result.stdout.split()


def get_remote_url(path: Path, name: str = "origin") -> str:
    """读取 git remote url; 不存在则返回空串。"""
    result = run_git(path, "remote", "get-url", name)
    return result.stdout.strip() if result.returncode == 0 else ""


def add_remote(path: Path, url: str, name: str = "origin") -> bool:
    """添加 remote; 已存在则更新其 url, 返回是否为新增。"""
    if has_remote(path, name):
        run_git(path, "remote", "set-url", name, url)
        return False
    result = run_git(path, "remote", "add", name, url)
    return result.returncode == 0


def working_tree_dirty(path: Path) -> list[str]:
    """返回未提交的变更文件列表(空 = 工作区干净)。"""
    result = run_git(path, "status", "--porcelain")
    if result.returncode != 0:
        return []
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def conflicted_files(path: Path) -> list[str]:
    """返回处于冲突状态(unmerged)的文件列表。"""
    result = run_git(path, "diff", "--name-only", "--diff-filter=U")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_rebase_in_progress(path: Path) -> bool:
    """是否处于未完成的 rebase 状态。"""
    for name in ("rebase-merge", "rebase-apply"):
        result = run_git(path, "rev-parse", "--git-path", name)
        if result.returncode == 0:
            location = Path(result.stdout.strip())
            if not location.is_absolute():
                location = path / location
            if location.exists():
                return True
    return False
