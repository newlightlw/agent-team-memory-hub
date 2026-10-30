"""零依赖 Web 服务 — http.server + REST API。

GET /                     前端页面(index.html)
GET /api/memories         所有记忆(?type=&source= 过滤)
GET /api/memories/<id>    单条详情(含版本历史)
GET /api/search?q=        关键字检索(全字段)
GET /api/stats            统计(总数 + 各来源数)

不依赖 FastAPI/Flask, 团队成员 `team-memory web` 即可开箱运行。
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..gitutil import run_git
from ..store import MemoryStore

STATIC_DIR = Path(__file__).resolve().parent / "static"

__all__ = ["serve"]


def _file_history(repo_root: Path, path: Path | None) -> list[dict[str, str]]:
    """返回文件的 git commit 列表(新在前): [{hash, date, subject}]。"""
    if path is None:
        return []
    rel = path.relative_to(repo_root)
    result = run_git(
        repo_root, "log", "--pretty=%h|%ad|%s", "--date=short", "--", str(rel)
    )
    commits: list[dict[str, str]] = []
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append(
                    {"hash": parts[0], "date": parts[1], "subject": parts[2]}
                )
    return commits


def _version_label(commits: list[dict[str, str]]) -> str:
    if not commits:
        return "未提交"
    return f"v{len(commits)} ({commits[0]['hash']})"


def _entry_to_dict(store: MemoryStore, entry: Any) -> dict[str, Any]:
    path = store.find_file(entry.id)
    commits = _file_history(store.root, path)
    return {
        "id": entry.id,
        "type": entry.type.value,
        "title": entry.title,
        "scope": entry.scope.value,
        "author": entry.author,
        "source": entry.source,
        "role": entry.role,
        "created": entry.created,
        "updated": entry.updated,
        "status": entry.status.value,
        "tags": list(entry.tags),
        "related": list(entry.related),
        "body": entry.body,
        "version": _version_label(commits),
        "commits": commits,
    }


def list_memories(
    store: MemoryStore,
    type_filter: str | None = None,
    source_filter: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in store.list_entries(type_filter):
        if source_filter and entry.source != source_filter:
            continue
        result.append(_entry_to_dict(store, entry))
    return result


def search_memories(store: MemoryStore, query: str) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return []
    terms = q.split()
    result: list[dict[str, Any]] = []
    for entry in store.list_entries():
        haystack = " ".join(
            [
                entry.title,
                entry.body,
                entry.author,
                entry.source,
                entry.role,
                *entry.tags,
                *entry.related,
                entry.id,
            ]
        ).lower()
        if all(term in haystack for term in terms):
            result.append(_entry_to_dict(store, entry))
    return result


def stats(store: MemoryStore) -> dict[str, Any]:
    entries = store.list_entries()
    sources: dict[str, int] = {}
    types: dict[str, int] = {}
    for entry in entries:
        src = entry.source or "未标注"
        sources[src] = sources.get(src, 0) + 1
        types[entry.type.value] = types.get(entry.type.value, 0) + 1
    return {"total": len(entries), "sources": sources, "types": types}


def inbox_list(store: MemoryStore, status: str = "pending_review") -> list[dict[str, Any]]:
    """列出 inbox 候选记忆(status='all' 不过滤)。"""
    return [
        _entry_to_dict(store, entry)
        for entry in store.list_inbox(status_filter=status)
    ]


def _make_handler(store: MemoryStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass  # 静默访问日志

        def _send_json(self, data: Any, code: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, name: str) -> None:
            path = (STATIC_DIR / name).resolve()
            # 防目录穿越
            if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists():
                self.send_error(404)
                return
            data = path.read_bytes()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(path.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            route = parsed.path

            if route in ("/", "/index.html"):
                self._send_static("index.html")
                return
            if route == "/api/memories":
                self._send_json(
                    list_memories(
                        store,
                        qs.get("type", [None])[0],
                        qs.get("source", [None])[0],
                    )
                )
                return
            if route.startswith("/api/memories/"):
                memory_id = route.rsplit("/", 1)[-1]
                entry = store.get_entry(memory_id)
                if entry is None:
                    self._send_json({"error": f"未找到记忆: {memory_id}"}, 404)
                else:
                    self._send_json(_entry_to_dict(store, entry))
                return
            if route == "/api/search":
                self._send_json(search_memories(store, qs.get("q", [""])[0]))
                return
            if route == "/api/stats":
                self._send_json(stats(store))
                return
            if route == "/api/inbox":
                self._send_json(
                    inbox_list(store, qs.get("status", ["pending_review"])[0])
                )
                return
            self.send_error(404)

        def _read_json(self) -> Any | None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return None

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            body = self._read_json()
            if not isinstance(body, dict):
                self._send_json({"error": "需要 JSON body"}, 400)
                return
            try:
                if route == "/api/propose":
                    from ..commands.inbox_cmd import propose_cmd
                    path = propose_cmd(
                        title=body["title"], type=body["type"],
                        scope=body.get("scope", "team"),
                        author=body.get("author", ""), source=body.get("source", ""),
                        role=body.get("role", ""),
                        tags=tuple(body.get("tags", [])),
                        related=tuple(body.get("related", [])),
                        evidence=tuple(body.get("evidence", [])),
                        confidence=body.get("confidence", "medium"),
                        note=body.get("note", ""), root=store.root,
                    )
                    self._send_json({"ok": True, "path": str(path)})
                elif route.startswith("/api/approve/"):
                    mid = route.rsplit("/", 1)[-1]
                    from ..commands.inbox_cmd import approve_cmd
                    path = approve_cmd(mid, root=store.root)
                    self._send_json({"ok": True, "id": mid, "path": str(path)})
                elif route.startswith("/api/decline/"):
                    mid = route.rsplit("/", 1)[-1]
                    from ..commands.inbox_cmd import decline_cmd
                    path = decline_cmd(
                        mid, root=store.root, reason=body.get("reason", "")
                    )
                    self._send_json({"ok": True, "id": mid, "path": str(path)})
                else:
                    self.send_error(404)
            except KeyError as exc:
                self._send_json({"error": f"缺少字段: {exc}"}, 400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 400)

    return Handler


def serve(
    store: MemoryStore,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    public_url: str = "",
) -> None:
    """启动 Web 服务(阻塞)。"""
    handler = _make_handler(store)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = public_url.strip() or f"http://{host}:{port}"
    print(f"team-memory web 已启动: {url}   (Ctrl+C 退出)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
