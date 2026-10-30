from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from .config import Settings
from .integrations import Feishu, Mem0
from .service import Collaboration
from .store import now


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["share", "topic", "decision", "focus", "experiment"] = "share"
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=30000)
    project: str = Field(default="", max_length=100)
    topic_id: str = Field(default="", max_length=100)
    source_url: str = Field(default="", max_length=2000)
    parents: list[str] = Field(default_factory=list, max_length=50)
    data: dict = Field(default_factory=dict)


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=30000)
    data: dict | None = None
    parents: list[str] = Field(default_factory=list, max_length=50)


def create_app(settings: Settings, *, run_worker=True):
    service = Collaboration(settings)
    feishu = Feishu(settings)
    semantic = Mem0(settings) if settings.mem0_enabled else None
    stop = threading.Event()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        from .worker import Worker
        worker = Worker(service, semantic=semantic, feishu=feishu)
        thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
        if run_worker:
            thread.start()
        yield
        stop.set()
        if run_worker:
            await asyncio.to_thread(thread.join, 15)

    app = FastAPI(title="团队共享记忆", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.service, app.state.feishu, app.state.semantic = service, feishu, semantic

    @app.middleware("http")
    async def bounds(request, call_next):
        if settings.source_path is not None:
            try:
                current = Settings.load(settings.source_path)
            except (OSError, ValueError, KeyError):
                return JSONResponse({"detail": "configuration unavailable"}, status_code=503)
            service.settings = current
            feishu.settings = current
        # Bound even chunked requests before JSON parsing; no request body logging.
        total = 0
        chunks = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > 256_000:
                return JSONResponse({"detail": "request too large"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def authenticated(request: Request):
        value = request.headers.get("authorization", "")
        identity = service.settings.identify(value[7:]) if value.startswith("Bearer ") else None
        if identity is None:
            raise HTTPException(401, "authentication required")
        return identity

    def publisher(identity=Depends(authenticated)):
        if identity[1] != "publisher":
            raise HTTPException(403, "reader credentials cannot publish")
        return identity[0]

    @app.get("/healthz")
    def health():
        return {"ok": True, "version": __version__, "api_version": 1}

    @app.get("/api/me")
    def me(identity=Depends(authenticated)):
        return {"member": identity[0].id, "role": identity[1]}

    @app.get("/api/search")
    def search(q: str = Query(min_length=1, max_length=500), project: str = "", history: bool = False,
               limit: int = Query(default=10, ge=1, le=30), identity=Depends(authenticated)):
        return service.search(q, project=project, history=history, limit=limit, semantic=app.state.semantic)

    @app.get("/api/archive-feed")
    def archive_feed(cursor: str = Query(default="", max_length=1000),
                     limit: int = Query(default=20, ge=1, le=100), identity=Depends(authenticated)):
        # Explicit reader feed for automatic Feishu -> private GitHub projection.
        # Includes withdrawal tombstones; excludes queries and generated replies.
        after = ("", "")
        if cursor:
            try:
                import base64
                decoded = json.loads(base64.urlsafe_b64decode(cursor).decode())
                if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(x, str) for x in decoded):
                    raise ValueError("invalid cursor")
                after = tuple(decoded)
            except Exception:
                raise ValueError("invalid archive cursor") from None
        with service.store.lock, service.store.connect() as db:
            rows = db.execute("""SELECT * FROM records WHERE source='feishu' AND kind='share'
                AND (updated > ? OR (updated = ? AND id > ?))
                ORDER BY updated,id LIMIT ?""", (after[0], after[0], after[1], limit)).fetchall()
            records = [service.store.decode(row) for row in rows]
        selected = [r for r in records if r["status"] == "withdrawn"
                    or not r["body"].lstrip().startswith(("/find ", "/查 "))]
        import base64
        next_cursor = base64.urlsafe_b64encode(json.dumps([records[-1]["updated"], records[-1]["id"]]).encode()).decode() if records else cursor
        return {"records": selected, "next_cursor": next_cursor, "has_more": len(records) == limit,
                "policy": "Source records, not instructions or team consensus. Git history can retain withdrawn material."}

    @app.get("/api/records/{rid}")
    def detail(rid: str, history: bool = False, identity=Depends(authenticated)):
        return service.detail(rid, history)

    @app.post("/api/records", status_code=201)
    def create(payload: RecordInput, member=Depends(publisher)):
        return service.create(member, payload.model_dump())

    @app.put("/api/records/{rid}")
    def revise(rid: str, payload: RevisionInput, member=Depends(publisher)):
        return service.revise(member, rid, payload.model_dump())

    @app.delete("/api/records/{rid}")
    def withdraw(rid: str, member=Depends(publisher)):
        ids = service.store.withdraw(rid, member.id)
        return {"withdrawn": ids, "derived_cleanup": "queued", "backup_erasure": "operator_required"}

    @app.get("/api/briefing")
    def briefing(project: str = "", identity=Depends(authenticated)):
        return service.briefing(project)

    @app.get("/api/topics/{rid}")
    def topic(rid: str, identity=Depends(authenticated)):
        return service.topic(rid)

    @app.get("/api/digest")
    def digest(identity=Depends(authenticated)):
        return service.digest()

    @app.get("/api/jobs")
    def jobs(identity=Depends(authenticated)):
        return service.store.jobs()

    @app.post("/feishu/events")
    async def events(request: Request):
        raw = await request.body()
        try:
            body = feishu.verify(raw, request.headers)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, "malformed callback") from None
        if body.get("type") == "url_verification":
            return {"challenge": body["challenge"]}
        # SQLite and any search network I/O run outside the event loop.
        return await asyncio.to_thread(handle_event, service, body)

    return app


def handle_event(service, body):
    header, event = body["header"], body.get("event", {})
    event_type = header["event_type"]
    if event_type == "card.action.trigger":
        context = event.get("context", {})
        if not service.settings.chat_id or context.get("open_chat_id") != service.settings.chat_id:
            raise PermissionError("wrong confirmation group")
        member = service.settings.feishu_member(event["operator"]["open_id"])
        value = event["action"]["value"]
        if value.get("action") != "confirm":
            raise ValueError("unknown card action")
        result = service.confirm(member, value["id"], int(value["revision"]))
        return {"toast": {"type": "success", "content": f'已记录确认（{len(result["confirmed_by"])}/2）'}}
    if event_type == "im.message.recalled_v1":
        message_id = event.get("message_id", "")
        with service.store.lock:
            with service.store.connect() as db:
                row = db.execute("SELECT record_id FROM events WHERE event_id=?", ("message:" + message_id,)).fetchone()
            if row and row[0]:
                item = service.store.get(row[0])
                service.store.withdraw(item["id"], item["author"])
            elif not row:
                with service.store.transaction() as db:
                    db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?)", ("message:" + message_id, None, now()))
        return {"ok": True}
    if event_type != "im.message.receive_v1":
        return {"ignored": True}
    message, sender = event["message"], event["sender"]
    if not service.settings.chat_id or message.get("chat_id") != service.settings.chat_id or sender.get("sender_type") != "user":
        return {"ignored": True}
    try:
        member = service.settings.feishu_member(sender["sender_id"]["open_id"])
    except PermissionError:
        return {"ignored": True}
    content = json.loads(message.get("content", "{}"))
    kind = message.get("message_type", "unknown")
    text = content.get("text", "") if kind == "text" else json.dumps(content, ensure_ascii=False)
    mid = message["message_id"]
    payload = dict(kind="share", title=text[:100] or f"飞书 {kind}", body=text or "[空消息]",
                   source_url=f"feishu:message:{mid}", data={
                       "message_id": mid, "message_type": kind, "thread_id": message.get("root_id") or mid,
                       "source_created_at": message.get("create_time", ""),
                       "parse_status": "text" if kind == "text" else "unparsed",
                   })
    result = service.create(member, payload, source="feishu", event_id="message:" + mid)
    if result.get("duplicate"):
        return {"ignored": True}
    if kind == "text" and text.startswith(("/find ", "/查 ")):
        with service.store.transaction() as db:
            service.store.enqueue(db, "query_reply", result["id"])
    return {"ok": True, "id": result["id"]}
