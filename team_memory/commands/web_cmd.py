"""team-memory web — 启动 Web 可视化管理服务。"""

from __future__ import annotations

import errno
from pathlib import Path

from rich.console import Console

from ..config import load_config
from ..store import MemoryStore
from ..web import serve

__all__ = ["web_cmd", "resolve_web_bind", "format_port_in_use_message"]


def resolve_web_bind(
    root: Path,
    *,
    host: str | None = None,
    port: int | None = None,
) -> tuple[str, int, str]:
    """从 CLI 参数 + 记忆仓库 .env 解析 web 绑定与对外 URL。"""
    config = load_config(root / ".env")
    resolved_host = host if host is not None else config.web_host
    resolved_port = port if port is not None else config.web_port
    public_url = config.web_public_url.strip()
    if not public_url:
        display_host = "127.0.0.1" if resolved_host in ("0.0.0.0", "::") else resolved_host
        public_url = f"http://{display_host}:{resolved_port}"
    return resolved_host, resolved_port, public_url


def format_port_in_use_message(port: int, public_url: str) -> str:
    """端口被占用时的友好提示(团队共享实例场景)。"""
    return (
        f"端口 {port} 已被占用 — 团队 Web 通常只需**一台机器启动一次**。\n"
        f"请直接在浏览器打开团队固定地址: {public_url}\n"
        "若你是管理员且服务未运行, 检查 systemd/启动脚本; "
        "本地调试可换端口: team-memory web --port 8766"
    )


def web_cmd(
    root: Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    open_browser: bool = True,
    console: Console | None = None,
) -> None:
    """启动 Web 可视化(阻塞; Ctrl+C 退出)。"""
    console = console or Console()
    store = MemoryStore.open(root)
    resolved_host, resolved_port, public_url = resolve_web_bind(
        store.root, host=host, port=port
    )
    console.print("[bold green]team-memory web[/]")
    console.print(f"  仓库: {store.root}")
    console.print(f"  记忆: {len(store.list_entries())} 条")
    console.print(f"  监听: http://{resolved_host}:{resolved_port}")
    console.print(f"  团队地址: [bold cyan]{public_url}[/]")
    if resolved_host in ("0.0.0.0", "::"):
        console.print(
            "  [dim]局域网组员请用「团队地址」访问, 无需各自再启动 web[/]"
        )
    try:
        serve(
            store,
            host=resolved_host,
            port=resolved_port,
            open_browser=open_browser,
            public_url=public_url,
        )
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES):
            console.print(f"[red]✗[/] {format_port_in_use_message(resolved_port, public_url)}")
            raise SystemExit(1) from exc
        raise
