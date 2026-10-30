from __future__ import annotations
import hmac
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import Accounts
from .data import Memories

STATIC = Path(__file__).parent / 'static'


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def create_app(config, *, source=None):
    origin = config['public_url'].rstrip('/')
    parsed = urlsplit(origin)
    secure = config.get('secure_cookie', True)
    if not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.scheme not in ('http', 'https') or secure and parsed.scheme != 'https':
        raise ValueError('public_url must be an origin; production requires HTTPS')
    accounts = Accounts(config['auth_db'])
    memories = source or Memories(config)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.accounts, app.state.memories = accounts, memories
    cookie = '__Host-team_memory_session' if secure else 'team_memory_session'

    @app.middleware('http')
    async def security(request, call_next):
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > 8192:
            return JSONResponse({'detail': '请求过大'}, status_code=413)
        # Login/logout accept bounded JSON only; do not buffer arbitrary uploads.
        if request.method == 'POST':
            body = b''
            async for part in request.stream():
                body += part
                if len(body) > 8192:
                    return JSONResponse({'detail': '请求过大'}, status_code=413)
            request._body = body
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    def active_member(name):
        path = config.get("members_config")
        if not path:
            return True  # Existing independent viewer configs remain compatible.
        try:
            from ..collaboration.config import Settings
            return any(m.id == name and m.active for m in Settings.load(Path(path)).members)
        except (ValueError, OSError, KeyError):
            return False

    def user(request: Request):
        session = accounts.session(request.cookies.get(cookie))
        if session is None or not active_member(session["username"]):
            raise HTTPException(401, '请先登录')
        return session

    def same_origin(request):
        if request.headers.get('origin') != origin:
            raise HTTPException(403, '来源校验失败')

    @app.get('/healthz')
    def health():
        return {'ok': True, 'service': 'team-memory-viewer'}

    @app.post('/api/login')
    def login(payload: Login, request: Request):
        same_origin(request)
        if not active_member(payload.username):
            raise HTTPException(401, "账号或密码错误")
        result, error = accounts.login(payload.username, payload.password, request.client.host)
        if not result:
            raise HTTPException(429 if error == 'limited' else 401, '尝试过于频繁，请稍后再试' if error == 'limited' else '账号或密码错误')
        response = JSONResponse({'username': result['username'], 'csrf': result['csrf']})
        response.set_cookie(cookie, result['token'], max_age=14 * 86400, secure=secure, httponly=True, samesite='strict', path='/')
        return response

    @app.get('/api/me')
    def me(session=Depends(user)):
        return session

    @app.post('/api/logout')
    def logout(request: Request, session=Depends(user)):
        same_origin(request)
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, '请求校验失败')
        accounts.logout(request.cookies.get(cookie))
        response = JSONResponse({'ok': True})
        response.delete_cookie(cookie, secure=secure, httponly=True, samesite='strict', path='/')
        return response

    @app.get('/api/memories')
    def listing(q: str = Query(default='', max_length=500), origin: str = Query(default='all', pattern='^(all|feishu|agent)$'),
                author: str = Query(default='', max_length=64), offset: int = Query(default=0, ge=0), session=Depends(user)):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        snapshot = memories.snapshot()
        rows = snapshot['records']
        stats = {'total': len(rows), 'feishu': sum(r['origin'] == 'feishu' for r in rows),
                 'agent': sum(r['origin'] == 'agent' for r in rows), 'summarized': sum(r['summarized'] for r in rows)}
        terms = q.casefold().split()
        filtered = [r for r in rows if (origin == 'all' or r['origin'] == origin) and (not author or r['author'] == author)
                    and all(t in (r['title'] + ' ' + r['body'] + ' ' + r['author'] + ' ' + r['source']).casefold() for t in terms)]
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        days = [(today - timedelta(days=n)).isoformat() for n in reversed(range(7))]
        return {k: v for k, v in snapshot.items() if k != 'records'} | {
            'records': [{k: v for k, v in r.items() if k != 'body'} | {'preview': r['body'][:200]} for r in filtered[offset:offset+50]],
            'total': len(filtered), 'has_more': offset + 50 < len(filtered), 'stats': stats,
            'authors': sorted({r['author'] for r in rows}), 'timeline': [{'date': day, 'count': sum(r['created'].startswith(day) for r in rows)} for day in days]}

    @app.get('/api/memory')
    def detail(key: str, session=Depends(user)):
        row = next((r for r in memories.snapshot(force=True)['records'] if r['key'] == key), None)
        if row is None:
            raise HTTPException(404, '记忆不存在或已撤回')
        return row

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in ('app.js', 'style.css'):
            raise HTTPException(404)
        return FileResponse(STATIC / name)

    return app
