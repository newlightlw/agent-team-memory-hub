import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient
from team_share.viewer.app import create_app
from team_share.viewer.auth import Accounts
from team_share.viewer.data import Memories
from team_share.models import MemoryEntry, MemoryType, serialize_memory
from team_share.collaboration.store import Store


@pytest.fixture
def viewer(tmp_path):
    cfg = dict(public_url='https://team.example', secure_cookie=True, auth_db=str(tmp_path/'auth.sqlite'),
               feishu_db=str(tmp_path/'missing.sqlite'), git_root=str(tmp_path/'git'), repo='example/private')
    class Source:
        def snapshot(self, **kwargs):
            return {'records':[dict(key='git:a',id='a',title='归档验收',body='purpose evidence deep_keyword <script>alert(1)</script>',
                    author='vayne',source='codex',created='2026-10-30',updated='2026-10-30',origin='agent',summarized=True,status='active',version='abc',git_url='')],
                    'commit':'abc','git_synced_at':'','warnings':[]}
    app = create_app(cfg, source=Source())
    file=tmp_path/'credentials.json'
    app.state.accounts.create(['vayne','kiki'],file)
    return app,cfg,json.loads(file.read_text()),file


def login(client, passwords, who='vayne'):
    return client.post('/api/login', headers={'Origin':'https://team.example'}, json={'username':who,'password':passwords[who]})


def test_viewer_auth_boundaries_sessions_logout_and_restart(viewer):
    app,cfg,passwords,file=viewer
    assert set(passwords)=={'vayne','kiki'} and all(len(p)==16 for p in passwords.values())
    assert file.stat().st_mode & 0o077 == 0
    with TestClient(app,base_url='https://team.example') as c:
        for path in ['/api/me','/api/memories','/api/memory?key=git:a']:
            assert c.get(path).status_code==401
        assert 'deep_keyword' not in c.get('/').text
        assert c.get('/assets/anything.json').status_code==404
        assert c.post('/api/login',json={'username':'vayne','password':passwords['vayne']}).status_code==403
        response=login(c,passwords)
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie and 'Domain=' not in cookie
        assert c.get('/api/memories?q=deep_keyword').json()['total']==1
        assert c.get('/api/memories?q=absent').json()['total']==0
        assert c.get('/api/memory?key=git:a').json()['body'].endswith('</script>')
        assert "script-src 'self'" in c.get('/').headers['content-security-policy']
        assert c.get('/api/memories').headers['cache-control']=='no-store'
        assert c.post('/api/logout',headers={'Origin':'https://team.example'}).status_code==403
        token=c.cookies.get('__Host-team_memory_session')
        assert Accounts(cfg['auth_db']).session(token)['username']=='vayne'
        assert c.post('/api/logout',headers={'Origin':'https://team.example','X-CSRF-Token':response.json()['csrf']}).status_code==200
        assert Accounts(cfg['auth_db']).session(token) is None
        assert c.get('/api/memories').status_code==401
        assert login(c,passwords,'kiki').status_code==200
    with pytest.raises(ValueError):
        Accounts(cfg['auth_db']).create(['vayne','kiki'],file.parent/'new-credentials.json')
    raw=Path(cfg['auth_db']).read_bytes()
    assert all(p.encode() not in raw for p in passwords.values())


def test_login_rate_limit_and_no_default_credentials(viewer):
    app,cfg,passwords,file=viewer
    with TestClient(app,base_url='https://team.example') as c:
        for _ in range(10):
            assert c.post('/api/login',headers={'Origin':'https://team.example'},json={'username':'vayne','password':'wrong'}).status_code==401
        assert login(c,passwords).status_code==429
    assert not (file.parent/'new-credentials.json').exists()


def test_merge_feishu_git_preserves_author_and_withdrawal(tmp_path):
    store=Store(tmp_path/'service')
    with store.transaction() as db:
        source=store.create(db,kind='share',author='kiki',title='来源',body='原始资料',source='feishu')
    root=tmp_path/'git';root.mkdir()
    def git(*args):subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    git('init');git('config','user.name','Synthetic');git('config','user.email','synthetic@localhost')
    directory=root/'memory/project';directory.mkdir(parents=True)
    body='# 整理版\n\n来源状态：active; revision=1\n\n## 目的与背景\n\n目的\n\n## 来源与证据\n\n- '+source['id']+'\n\n## 原始资料（来源数据）\n\n原始资料'
    entry=MemoryEntry(id='mem-20261030-archive_test-001',type=MemoryType.PROJECT,title='整理版',author='kiki',source='feishu',created='2026-10-30',body=body)
    (directory/'one.md').write_text(serialize_memory(entry));git('add','.');git('commit','-m','synthetic source')
    reader=Memories(dict(feishu_db=str(store.path),git_root=str(root),repo='example/private'))
    result=reader.snapshot()
    assert len(result['records'])==1 and result['records'][0]['author']=='kiki' and result['records'][0]['summarized']
    with store.transaction() as db:
        changed=store.get(source['id'],db)
        changed.update(body='修订后的最新原文',revision=2)
        store.save(db,changed)
    fresh=reader.snapshot(force=True)['records']
    assert len(fresh)==1 and not fresh[0]['summarized'] and fresh[0]['body']=='修订后的最新原文'
    store.withdraw(source['id'],'kiki');reader.cached_at=0
    assert reader.snapshot()['records']==[]
    assert '原始资料' not in json.dumps(reader.snapshot(),ensure_ascii=False)
