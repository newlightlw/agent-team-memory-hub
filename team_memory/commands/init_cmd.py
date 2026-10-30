"""team-memory init — 在指定路径生成记忆仓库骨架。

生成: 标记文件 .team-memory.yml + 仓库骨架(README/CLAUDE.md/rules/.gitignore/.env)
+ 五类记忆的 body 模板 + 示例种子记忆 + git 初始化 + remote(若已配真实地址)。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console

from ..config import load_config
from ..gitutil import add_remote, ensure_git_identity, git_init, is_git_repo
from ..models import TYPE_DIR, today_iso
from ..store import MARKER_FILE
from ..templating import TEMPLATES_DIR, copy_template_tree

__all__ = ["init_cmd"]


def _write_marker(root: Path, team_name: str) -> None:
    data = {
        "team_name": team_name,
        "version": "0.1.0",
        "tool": "team-memory",
        "created": today_iso(),
    }
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    (root / MARKER_FILE).write_text(text + "\n", encoding="utf-8")


def init_cmd(
    path: Path,
    team_name: str,
    author: str,
    *,
    force: bool = False,
    console: Console | None = None,
) -> Path:
    """初始化记忆仓库; 返回仓库根路径。"""
    console = console or Console()
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)

    from ..store import MemoryStore
    MemoryStore(root).assert_writable()

    # 1. 标记文件(标识记忆仓库根)
    _write_marker(root, team_name)

    # 2. 仓库骨架(README / CLAUDE.md / rules / .gitignore / .env.example)
    variables = {"team_name": team_name, "author": author}
    written = copy_template_tree(
        TEMPLATES_DIR / "repo", root, variables, overwrite=force
    )

    # 3. 五类记忆的 body 模板 -> memory/{dir}/_template.md
    for type_key, dir_name in TYPE_DIR.items():
        src = TEMPLATES_DIR / "types" / f"{type_key}.md"
        if not src.exists():
            continue
        target = root / "memory" / dir_name / "_template.md"
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(target)

    # 4. 示例种子记忆
    example = TEMPLATES_DIR / "examples" / "product-overview.md"
    if example.exists():
        seed = root / "memory" / "project" / "product-overview.md"
        if not seed.exists() or force:
            seed.parent.mkdir(parents=True, exist_ok=True)
            seed.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(seed)

    # 5. 生成 .env(从 .env.example, 便于用户直接填 url)
    env_example = root / ".env.example"
    env_file = root / ".env"
    if env_example.exists() and (not env_file.exists() or force):
        env_file.write_text(
            env_example.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # 6. git init
    if not is_git_repo(root):
        git_init(root)
        console.print("[green]✓[/] 初始化 git 仓库")
    else:
        console.print("[dim]git 仓库已存在, 跳过 init[/]")

    # 7. git 身份检查
    name, email = ensure_git_identity()
    if not name or not email:
        console.print(
            "[yellow]⚠ 全局 git 身份未配置, 建议先运行:[/]\n"
            "  git config --global user.name '你的名字'\n"
            "  git config --global user.email '你的邮箱'"
        )

    # 8. Git remote(若已填真实地址)
    config = load_config(env_path=env_file)
    if config.has_gitea_remote and not config.is_remote_placeholder:
        add_remote(root, config.resolved_remote_url(), "origin")
        console.print(
            f"[green]✓[/] 配置 origin -> {config.gitea_remote_url}"
        )
    else:
        console.print(
            f"[dim]Git remote 未配置(占位符)。编辑 {root}/.env 填入 "
            "GITEA_REMOTE_URL 后运行 `team-memory sync`[/]"
        )

    console.print(f"\n[bold green]记忆仓库已就绪:[/] {root}")
    console.print(
        f"[dim]生成了 {len(written)} 个文件。下一步: 编辑 CLAUDE.md / memory/, "
        "用 `team-memory capture` 沉淀记忆。[/]"
    )
    return root
