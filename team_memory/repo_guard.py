"""记忆仓库路径校验 — 防止写入 agent-team-memory 工具仓库。"""

from __future__ import annotations

from pathlib import Path

from .config import load_config
from .gitutil import get_remote_url
from .store import MARKER_FILE, NotAMemoryRepoError, find_memory_root

__all__ = [
    "TOOL_REPO_NAME",
    "MEMORY_REPO_NAME",
    "resolve_memory_root",
    "assert_valid_memory_repo",
    "looks_like_tool_repo",
]

TOOL_REPO_NAME = "agent-team-memory"
MEMORY_REPO_NAME = "team-memory"


def looks_like_tool_repo(root: Path) -> bool:
    """路径是否像 agent-team-memory 工具源码仓库。"""
    return (root / "pyproject.toml").exists() and (root / "team_memory" / "cli.py").exists()


def assert_valid_memory_repo(root: Path) -> None:
    """确认 root 是 team-memory 数据仓库, 不是工具仓库。

    Raises:
        NotAMemoryRepoError: 缺少 .team-memory.yml
        ValueError: 路径或 remote 指向工具仓库
    """
    resolved = root.resolve()
    if looks_like_tool_repo(resolved):
        raise ValueError(
            f"当前路径是 {TOOL_REPO_NAME} 工具仓库, 不能在此沉淀记忆: {resolved}\n"
            f"记忆应写入独立的数据仓库(通常 ~/team-memory), 并用 -p 指定。"
        )
    if not (resolved / MARKER_FILE).exists():
        raise NotAMemoryRepoError(
            f"不是记忆仓库(缺少 {MARKER_FILE}): {resolved}\n"
            "请用 -p 指定 onboard 后的记忆仓库(如 ~/team-memory)。"
        )
    remote = get_remote_url(resolved)
    if not remote:
        cfg = load_config(resolved / ".env")
        remote = cfg.gitea_remote_url
    if remote and TOOL_REPO_NAME in remote:
        raise ValueError(
            f"Git remote 指向工具仓库({remote}), 记忆应推到 {MEMORY_REPO_NAME} 仓库。\n"
            f"请检查 {resolved}/.env 的 GITEA_REMOTE_URL。"
        )


def resolve_memory_root(explicit: Path | None = None) -> Path:
    """解析记忆仓库根路径(显式参数 > TEAM_MEMORY_ROOT > 向上查找 > ~/team-memory)。"""
    import os

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    env_root = os.environ.get("TEAM_MEMORY_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    found = find_memory_root()
    if found is not None:
        candidates.append(found)
    candidates.append(Path.home() / "team-memory")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / MARKER_FILE).exists():
            assert_valid_memory_repo(resolved)
            return resolved

    raise NotAMemoryRepoError(
        "找不到记忆仓库。请先 onboard, 或用 -p / TEAM_MEMORY_ROOT 指定路径。"
    )
