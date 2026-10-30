"""team-memory CLI 入口(typer)。

命令:
  init     初始化一个团队记忆仓库
  capture  沉淀一条记忆
  load     把团队记忆加载到目标项目(Claude Code 桥接)
  sync     与 Git 远程同步(pull + push)
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import typer
from rich.console import Console

from . import __version__
from .commands import bridges_doctor_cmd, capture_cmd, doctor_cmd, inbox_cmd, init_cmd, index_cmd, list_cmd, load_cmd, save_cmd, show_cmd, sync_cmd, update_cmd, validate_cmd, web_cmd
from .config import load_config
from .gitutil import GitError
from .models import MemoryValidationError
from .store import NotAMemoryRepoError

app = typer.Typer(
    name="team-memory",
    help="团队 Agent Memory 共享系统 — 加载 / 沉淀 / 同步团队记忆到 Git 远端",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()


def _show_version(value: bool) -> None:
    if value:
        console.print(f"team-memory {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_show_version,
        is_eager=True,
        help="显示版本号后退出",
    ),
) -> None:
    """团队 Agent Memory 共享系统。"""


@app.command()
def init(
    path: str = typer.Option(
        None, "-p", "--path",
        help="记忆仓库路径(默认 .env 的 DEFAULT_MEMORY_PATH 或 ./memory)",
    ),
    team: str = typer.Option(None, "-n", "--team", help="团队名"),
    author: str = typer.Option(None, "-a", "--author", help="默认作者"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的文件"),
) -> None:
    """初始化一个团队记忆仓库(目录骨架 + git + remote 占位配置)。"""
    config = load_config()
    init_cmd(
        Path(path or config.default_memory_path),
        team_name=team or config.team_name,
        author=author or config.default_author,
        force=force,
        console=console,
    )


@app.command()
def capture(
    title: str = typer.Argument(..., help="记忆标题"),
    type: str = typer.Option(
        ..., "-t", "--type",
        help="记忆类型: project / code / decision / error / skill",
    ),
    scope: str = typer.Option("team", "--scope", help="范围: team / project / module"),
    author: str = typer.Option(None, "-a", "--author"),
    via: str = typer.Option("", "--via", help="沉淀来源工具: claude/codex/hermes/trae"),
    role: str = typer.Option("", "--role", help="岗位: algorithm / data / product / fullstack"),
    tags: str = typer.Option(None, "--tags", help="逗号分隔的标签"),
    related: str = typer.Option(None, "--related", help="逗号分隔的关联记忆 id"),
    note: str = typer.Option(None, "--note", help="简短正文(不套模板时)"),
    from_file: str = typer.Option(None, "--from-file", help="从文件读取完整 body"),
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根(默认自动定位)"),
) -> None:
    """沉淀一条记忆(自动生成 id + frontmatter, 落盘, 不自动 commit)。"""
    config = load_config()
    try:
        capture_cmd(
            title=title,
            type=type,
            scope=scope,
            author=author or config.default_author,
            source=via,
            role=role,
            tags=tuple(t.strip() for t in tags.split(",") if t.strip()) if tags else (),
            related=tuple(r.strip() for r in related.split(",") if r.strip()) if related else (),
            note=note or "",
            from_file=from_file,
            root=Path(root) if root else None,
            console=console,
        )
    except (NotAMemoryRepoError, ValueError, MemoryValidationError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="沉淀记忆并 git commit(「提交一下」推荐用此命令, 避免写错仓库)")
def save(
    title: str = typer.Argument(..., help="记忆标题"),
    type: str = typer.Option(
        ..., "-t", "--type",
        help="记忆类型: project / code / decision / error / skill",
    ),
    scope: str = typer.Option("team", "--scope", help="范围: team / project / module"),
    author: str = typer.Option(None, "-a", "--author"),
    via: str = typer.Option("", "--via", help="沉淀来源工具: claude/codex/hermes/trae/cursor"),
    role: str = typer.Option("", "--role", help="岗位: algorithm / data / product / fullstack"),
    tags: str = typer.Option(None, "--tags", help="逗号分隔的标签"),
    related: str = typer.Option(None, "--related", help="逗号分隔的关联记忆 id"),
    note: str = typer.Option(None, "--note", help="简短正文"),
    from_file: str = typer.Option(None, "--from-file", help="从文件读取完整 body"),
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根(强烈建议显式指定)"),
    sync_after: bool = typer.Option(False, "--sync", help="commit 后立即 sync 到 Git 远端"),
) -> None:
    """在记忆数据仓库内 capture + git commit(可选 --sync)。"""
    config = load_config()
    try:
        save_cmd(
            title=title,
            type=type,
            scope=scope,
            author=author or config.default_author,
            source=via,
            role=role,
            tags=tuple(t.strip() for t in tags.split(",") if t.strip()) if tags else (),
            related=tuple(r.strip() for r in related.split(",") if r.strip()) if related else (),
            note=note or "",
            from_file=from_file,
            root=Path(root) if root else None,
            do_sync=sync_after,
            console=console,
        )
    except (NotAMemoryRepoError, ValueError, MemoryValidationError, GitError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command()
def load(
    target: str = typer.Argument(
        None, help="目标项目路径(项目级模式必填; --global 时忽略)"
    ),
    tools: str = typer.Option(
        "claude,codex,hermes,trae", "--tools", help="逗号分隔的工具列表"
    ),
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    link: bool = typer.Option(False, "--link", help="项目级: 额外创建 .memory 软链"),
    global_mode: bool = typer.Option(
        False, "--global", help="注册到各工具全局配置(一次配好所有项目)"
    ),
    no_aux_skill: bool = typer.Option(
        False, "--no-aux-skill", help="不装 auto-commit-memory 辅助 skill"
    ),
) -> None:
    """把团队记忆加载到工具(--global 全局注册 / 默认项目级桥接)。"""
    try:
        load_cmd(
            Path(target) if target else None,
            tools=tuple(t.strip() for t in tools.split(",") if t.strip()),
            root=Path(root) if root else None,
            link=link,
            global_mode=global_mode,
            aux_skill=not no_aux_skill,
            console=console,
        )
    except (NotAMemoryRepoError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command()
def sync(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    push: bool = typer.Option(True, "--push/--no-push", help="是否 push"),
    pull: bool = typer.Option(True, "--pull/--no-pull", help="是否 pull"),
    force: bool = typer.Option(False, "--force", help="跳过工作区未提交预检"),
) -> None:
    """与 Git 远程同步(pull + push, 不自动 commit)。"""
    try:
        ok = sync_cmd(
            Path(root) if root else None,
            push=push,
            pull=pull,
            force=force,
            console=console,
        )
        if not ok:
            raise typer.Exit(1)
    except (NotAMemoryRepoError, ValueError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command("list", help="列出所有记忆(来源 / 时间 / 版本)")
def list_(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    type: str = typer.Option(None, "-t", "--type", help="按类型过滤"),
) -> None:
    try:
        list_cmd(Path(root) if root else None, type_filter=type, console=console)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="查看单条记忆详情 + git 版本历史")
def show(
    memory_id: str = typer.Argument(..., help="记忆 id, 如 mem-20260624-001"),
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
) -> None:
    try:
        show_cmd(memory_id, Path(root) if root else None, console=console)
    except (NotAMemoryRepoError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="启动 Web 可视化管理(来源/时间/版本 + 检索框)")
def web(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    port: int | None = typer.Option(None, "--port", help="端口(默认读 .env 的 WEB_PORT)"),
    host: str | None = typer.Option(None, "--host", help="监听地址(默认读 .env 的 WEB_HOST)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="不自动打开浏览器"),
) -> None:
    """启动 Web UI(阻塞, Ctrl+C 退出)。"""
    try:
        web_cmd(
            Path(root) if root else None,
            host=host,
            port=port,
            open_browser=not no_browser,
            console=console,
        )
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 1)


@app.command(help="更新一条记忆(--note 追加 / --from-file 替换 / --supersede 废弃)")
def update(
    memory_id: str = typer.Argument(..., help="记忆 id"),
    note: str = typer.Option(None, "--note", help="追加一段更新"),
    from_file: str = typer.Option(None, "--from-file", help="替换正文(读取文件)"),
    supersede: str = typer.Option(None, "--supersede", help="标记被取代, 传新 id"),
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
) -> None:
    try:
        update_cmd(
            memory_id,
            note=note,
            from_file=from_file,
            supersede=supersede,
            root=Path(root) if root else None,
            console=console,
        )
    except (NotAMemoryRepoError, ValueError, MemoryValidationError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="诊断仓库健康(解析失败/重复 id/悬空引用/缺 author)")
def doctor(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
) -> None:
    try:
        code = doctor_cmd(Path(root) if root else None, console=console)
        if code:
            raise typer.Exit(code)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="检查 Claude/Codex 等全局 skill 是否已安装(「提交一下」依赖此项)")
def check_bridges(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    tools: str = typer.Option(
        "claude,codex,hermes,trae", "--tools", help="要检查的工具, 逗号分隔"
    ),
) -> None:
    try:
        code = bridges_doctor_cmd(
            Path(root) if root else None,
            tools=tuple(t.strip() for t in tools.split(",") if t.strip()),
            console=console,
        )
        if code:
            raise typer.Exit(code)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="校验整个仓库(CI 用; 错误时退出码非 0)")
def validate(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
    strict: bool = typer.Option(False, "--strict", help="warning 也算失败"),
) -> None:
    try:
        code = validate_cmd(Path(root) if root else None, strict=strict, console=console)
        if code:
            raise typer.Exit(code)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="生成各类型 _index.md 索引(按日期倒序, 便于浏览)")
def index(
    root: str = typer.Option(None, "-p", "--root", help="记忆仓库根"),
) -> None:
    try:
        index_cmd(Path(root) if root else None, console=console)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="提交候选记忆到 inbox(AI/未验证经验, 待人工 approve)")
def propose(
    title: str = typer.Argument(..., help="候选标题"),
    type: str = typer.Option(..., "-t", "--type", help="project/code/decision/error/skill"),
    scope: str = typer.Option("team", "--scope"),
    author: str = typer.Option(None, "-a", "--author"),
    via: str = typer.Option("", "--via", help="来源工具 claude/codex/hermes/trae"),
    role: str = typer.Option("", "--role"),
    tags: str = typer.Option(None, "--tags"),
    related: str = typer.Option(None, "--related"),
    evidence: str = typer.Option(None, "--evidence", help="来源证据, 逗号分隔(PR/会议/bad case)"),
    confidence: str = typer.Option("medium", "--confidence", help="low/medium/high"),
    note: str = typer.Option(None, "--note"),
    from_file: str = typer.Option(None, "--from-file"),
    root: str = typer.Option(None, "-p", "--root"),
) -> None:
    try:
        inbox_cmd.propose_cmd(
            title, type, scope=scope, author=author or "", source=via, role=role,
            tags=tuple(t.strip() for t in tags.split(",") if t.strip()) if tags else (),
            related=tuple(r.strip() for r in related.split(",") if r.strip()) if related else (),
            evidence=tuple(e.strip() for e in evidence.split(",") if e.strip()) if evidence else (),
            confidence=confidence, note=note or "", from_file=from_file,
            root=Path(root) if root else None, console=console,
        )
    except (NotAMemoryRepoError, ValueError, MemoryValidationError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="审核 inbox 候选(列出 pending_review)")
def review(
    root: str = typer.Option(None, "-p", "--root"),
    status: str = typer.Option("pending_review", "--status", help="pending_review/all/declined"),
) -> None:
    try:
        inbox_cmd.review_cmd(Path(root) if root else None, status=status, console=console)
    except NotAMemoryRepoError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="通过候选 → 转正式记忆(active)")
def approve(
    memory_id: str = typer.Argument(..., help="候选 id"),
    root: str = typer.Option(None, "-p", "--root"),
) -> None:
    try:
        inbox_cmd.approve_cmd(memory_id, Path(root) if root else None, console=console)
    except (NotAMemoryRepoError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)


@app.command(help="拒绝候选(标 declined, 留 inbox 供追溯)")
def decline(
    memory_id: str = typer.Argument(..., help="候选 id"),
    reason: str = typer.Option("", "--reason"),
    root: str = typer.Option(None, "-p", "--root"),
) -> None:
    try:
        inbox_cmd.decline_cmd(memory_id, Path(root) if root else None, reason=reason, console=console)
    except (NotAMemoryRepoError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1)



@app.command("join")
def join_shared(
    repo: str = typer.Argument(..., help="Private GitHub team-memory repository URL"),
    root: Path = typer.Option(..., "-p", "--root", help="New member cache directory"),
    branch: str = typer.Option("main", "--branch"),
):
    """Clone or safely refresh a read-only team cache; never overwrite a writer checkout."""
    from .sharing import join

    try:
        console.print(str(join(repo, root, branch=branch)))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@app.command("refresh")
def refresh_shared(root: Path = typer.Option(..., "-p", "--root")):
    """Pull current Git knowledge with fast-forward only; no push, reset or auto-commit."""
    try:
        if not sync_cmd(root, push=False, console=console):
            raise typer.Exit(1)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@app.command("stage-from-team")
def stage_from_team(
    record_id: str,
    reader: Path = typer.Option(
        ..., "--reader", help="Private READER credentials; never publisher credentials"
    ),
    author: str = typer.Option(..., "--author"),
    type_: str = typer.Option("project", "--type"),
    outbox: Path = typer.Option(Path("~/.config/team-memory-hub/outbox"), "--outbox"),
):
    """Copy ONE selected service record to a PRIVATE LOCAL draft, preserving provenance. No upload."""
    from .sharing import stage_team_record

    try:
        if "publisher" in reader.name.lower():
            raise ValueError("Use reader credentials, never publisher credentials")
        console.print(
            str(
                stage_team_record(record_id, reader.expanduser(), outbox, author, type_)
            )
        )
        console.print(
            "uploaded=false; source is a snapshot and must be rechecked before publishing"
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]Local draft not confirmed: {type(exc).__name__}[/]")
        raise typer.Exit(1)


@app.command("submit")
def submit_local_draft(
    candidate: Path,
    root: Path = typer.Option(..., "-p", "--root"),
    reader: Path | None = typer.Option(None, "--reader"),
):
    """HUMAN terminal review: local candidate -> writer inbox only, no automatic commit/push."""
    from .sharing import submit_draft

    try:
        console.print(
            str(
                submit_draft(
                    candidate.expanduser(),
                    root.expanduser(),
                    reader=reader.expanduser() if reader else None,
                )
            )
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
